"""Posture monitoring service."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gio, GLib
from enum import Enum
from typing import Optional, List

from praya.core import BaseService, ServiceStatus, DBusServiceMixin, NotificationManager
from .camera import CameraProcessor
from .calibration import CalibrationWindow, CalibrationData


class PostureStatus(Enum):
    """Posture-specific status."""
    STARTING = "Starting..."
    CALIBRATING = "Calibrating..."
    MONITORING = "Monitoring"
    GOOD_POSTURE = "Good Posture"
    SLOUCHING = "Slouching"
    AWAY = "Away"
    DISABLED = "Disabled"
    NO_CAMERA = "No Camera"
    CAMERA_ERROR = "Camera Error"


class PostureService(BaseService, DBusServiceMixin):
    """
    Posture monitoring service.

    Monitors user posture via webcam and sends notifications when slouching.
    """

    SERVICE_NAME = "posture"
    SERVICE_DESCRIPTION = "Posture monitoring using camera and pose detection"
    APPLICATION_ID = "com.github.praya.posture"
    DBUS_INTERFACE = "com.github.Praya.Posture"
    DBUS_PATH = "/com/github/Praya/Posture"

    def __init__(self):
        BaseService.__init__(self)
        DBusServiceMixin.__init__(self)

        self.posture_status = PostureStatus.STARTING
        self.calibration = CalibrationData()
        self.calibration_window: Optional[CalibrationWindow] = None
        self.notification_manager: Optional[NotificationManager] = None
        self.current_severity = 0.0

        self.consecutive_bad_frames = 0
        self.consecutive_good_frames = 0
        self.consecutive_no_detection = 0
        self.frame_threshold = 8
        self.away_frame_threshold = 15
        self.is_currently_slouching = False

        self.nose_y_history: List[float] = []
        self.smoothing_window = 5

        self.camera = CameraProcessor()
        self.camera.on_pose_detected = self._on_pose_detected
        self.camera.on_no_detection = self._on_no_detection
        self.camera.on_camera_error = self._on_camera_error

    def get_dbus_xml(self) -> str:
        """Return D-Bus interface definition."""
        return f"""
        <node>
            <interface name="{self.DBUS_INTERFACE}">
                <method name="GetStatus">
                    <arg direction="out" type="s" name="status"/>
                    <arg direction="out" type="d" name="severity"/>
                </method>
                <method name="Recalibrate"/>
                <signal name="PostureChanged">
                    <arg type="s" name="status"/>
                    <arg type="d" name="severity"/>
                </signal>
            </interface>
        </node>
        """

    def _setup_actions(self):
        """Setup application actions."""
        super()._setup_actions()

        recalibrate_action = Gio.SimpleAction.new("recalibrate", None)
        recalibrate_action.connect("activate", lambda a, p: self.start_calibration())
        self.add_action(recalibrate_action)

    def do_activate(self):
        """Called when the service is activated."""
        self.notification_manager = NotificationManager("Praya Posture")

        # Setup D-Bus
        self.setup_dbus()
        self.register_dbus_method("GetStatus", self._dbus_get_status)
        self.register_dbus_method("Recalibrate", self._dbus_recalibrate)

        print(f"Praya Posture Service")
        print("=" * 40)
        print(f"D-Bus: {self.DBUS_INTERFACE}")
        print(f"       Path: {self.DBUS_PATH}")
        print("Controls:")
        print("  - Press Ctrl+C to quit")
        print("")

        self.camera.start()
        GLib.timeout_add(1000, self.start_calibration)
        self.hold()

    def _dbus_get_status(self, params, invocation):
        """Handle GetStatus D-Bus method."""
        status_str = self._get_status_string()
        result = GLib.Variant("(sd)", (status_str, self.current_severity))
        invocation.return_value(result)

    def _dbus_recalibrate(self, params, invocation):
        """Handle Recalibrate D-Bus method."""
        GLib.idle_add(self.start_calibration)
        invocation.return_value(None)

    def _get_status_string(self) -> str:
        """Get status as string for D-Bus."""
        return {
            PostureStatus.GOOD_POSTURE: "good",
            PostureStatus.SLOUCHING: "slouching",
            PostureStatus.AWAY: "away",
            PostureStatus.CALIBRATING: "calibrating",
            PostureStatus.MONITORING: "good",
            PostureStatus.DISABLED: "disabled",
        }.get(self.posture_status, "unknown")

    def start_calibration(self) -> bool:
        if self.calibration_window:
            return False

        self._set_posture_status(PostureStatus.CALIBRATING)

        self.calibration_window = CalibrationWindow(
            self,
            on_complete=self._finish_calibration,
            on_cancel=self._cancel_calibration
        )
        self.calibration_window.present()

        return False

    def _finish_calibration(self, values: List[float], tolerance: float):
        self.calibration_window = None

        if len(values) >= 4:
            max_y = max(values)
            min_y = min(values)
            avg_y = sum(values) / len(values)

            self.calibration.good_posture_y = min_y
            self.calibration.bad_posture_y = max_y
            self.calibration.neutral_y = avg_y
            self.calibration.posture_range = abs(max_y - min_y)
            self.calibration.tolerance = tolerance
            self.calibration.is_calibrated = True

            print(f"Calibration: range={min_y:.3f}-{max_y:.3f}, tolerance={tolerance:.0%}")

            self._set_posture_status(PostureStatus.MONITORING)
            if self.notification_manager:
                self.notification_manager.send(
                    "Calibration Complete",
                    "Praya is now monitoring your posture.",
                    urgency="low"
                )
        else:
            self._cancel_calibration()

    def _cancel_calibration(self):
        self.calibration_window = None
        self.calibration.is_calibrated = True
        self._set_posture_status(PostureStatus.MONITORING)

    def _on_pose_detected(self, nose_y: float):
        if self.calibration_window:
            self.calibration_window.update_nose_y(nose_y)
            return

        if not self.is_enabled or not self.calibration.is_calibrated:
            return

        self.consecutive_no_detection = 0
        self._evaluate_posture(nose_y)

    def _on_no_detection(self):
        self.consecutive_no_detection += 1
        self.consecutive_bad_frames = 0
        self.consecutive_good_frames = 0

        if not self.is_enabled or not self.calibration.is_calibrated:
            return

        if self.consecutive_no_detection >= self.away_frame_threshold:
            self._set_posture_status(PostureStatus.AWAY)

    def _on_camera_error(self, error: str):
        self._set_posture_status(PostureStatus.CAMERA_ERROR)
        print(f"Camera error: {error}")

    def _smooth_nose_y(self, raw_y: float) -> float:
        self.nose_y_history.append(raw_y)
        if len(self.nose_y_history) > self.smoothing_window:
            self.nose_y_history.pop(0)
        return sum(self.nose_y_history) / len(self.nose_y_history)

    def _evaluate_posture(self, current_y: float):
        smoothed_y = self._smooth_nose_y(current_y)

        # Slouching = head drops BELOW the calibrated bad posture position (higher Y value)
        slouch_amount = smoothed_y - self.calibration.bad_posture_y

        # Normalize to 0-1 based on posture range
        if self.calibration.posture_range > 0:
            normalized_slouch = slouch_amount / self.calibration.posture_range
        else:
            normalized_slouch = slouch_amount / 0.1  # Fallback

        normalized_slouch = max(0.0, normalized_slouch)  # Can't be negative

        # Check if slouch exceeds user-set tolerance
        # Hysteresis: need more deviation to enter slouch, less to exit
        enter_threshold = self.calibration.tolerance
        exit_threshold = self.calibration.tolerance * 0.7

        threshold = exit_threshold if self.is_currently_slouching else enter_threshold
        is_bad_posture = normalized_slouch > threshold

        if is_bad_posture:
            self.consecutive_bad_frames += 1
            self.consecutive_good_frames = 0

            if self.consecutive_bad_frames >= self.frame_threshold:
                self.is_currently_slouching = True

                # Severity: how much over the threshold (0-1)
                severity = min(1.0, (normalized_slouch - threshold) / max(0.01, (1.0 - threshold)))

                self._set_posture_status(PostureStatus.SLOUCHING, severity)

                # Send notification
                if self.notification_manager:
                    self._notify_slouching(severity)
        else:
            self.consecutive_good_frames += 1
            self.consecutive_bad_frames = 0

            if self.consecutive_good_frames >= self.frame_threshold:
                self.is_currently_slouching = False
                self._set_posture_status(PostureStatus.GOOD_POSTURE)

    def _notify_slouching(self, severity: float):
        """Send slouching notification."""
        if severity < 0.3:
            body = "You're starting to slouch. Sit up straight!"
        elif severity < 0.6:
            body = "Your posture needs attention. Straighten your back!"
        else:
            body = "Poor posture detected! Please correct your position."

        self.notification_manager.send(
            "Posture Alert",
            body,
            icon="dialog-warning",
            urgency="normal" if severity < 0.5 else "critical"
        )

    def _set_posture_status(self, status: PostureStatus, severity: float = 0.0):
        if status != self.posture_status or (status == PostureStatus.SLOUCHING and severity != self.current_severity):
            self.posture_status = status
            self.current_severity = severity
            print(f"Status: {status.value}" + (f" (severity: {severity:.2f})" if severity > 0 else ""))

            # Emit D-Bus signal
            self.emit_dbus_signal(
                "PostureChanged",
                GLib.Variant("(sd)", (self._get_status_string(), severity))
            )

    def do_shutdown(self):
        self.camera.stop()
        if self.notification_manager:
            self.notification_manager.cleanup()
        self.cleanup_dbus()
        BaseService.do_shutdown(self)
