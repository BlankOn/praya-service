"""Posture monitoring service."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gio, GLib
from enum import Enum
from typing import Optional, List
import sys
import time

from praya.core import DBusServiceMixin, NotificationManager
from .camera import CameraProcessor
from .calibration import CalibrationWindow, CalibrationData


def log(msg):
    """Print and flush immediately."""
    print(msg)
    sys.stdout.flush()


class PostureStatus(Enum):
    """Posture-specific status."""
    STARTING = "starting"
    CALIBRATING = "calibrating"
    MONITORING = "monitoring"
    GOOD_POSTURE = "good"
    SLOUCHING = "slouching"
    AWAY = "away"
    DISABLED = "disabled"
    NO_CAMERA = "no_camera"
    CAMERA_ERROR = "camera_error"


class PostureService(DBusServiceMixin):
    """
    Posture monitoring service.

    Monitors user posture via webcam and sends notifications when slouching.
    This service is managed by the Praya daemon and can be enabled/disabled
    via D-Bus commands.
    """

    SERVICE_NAME = "posture"
    SERVICE_DESCRIPTION = "Posture monitoring using camera and pose detection"
    DBUS_INTERFACE = "com.github.blankon.Praya.Posture"
    DBUS_PATH = "/com/github/blankon/Praya/Posture"

    def __init__(self, app):
        """
        Initialize posture service.

        Args:
            app: The parent Praya daemon application
        """
        DBusServiceMixin.__init__(self)

        self.app = app
        self.status = PostureStatus.STARTING
        self.is_enabled = False
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

        # Alert delay tracking
        self.slouch_start_time: Optional[float] = None
        self.alert_sent_for_current_slouch = False

        self.camera: Optional[CameraProcessor] = None

    def get_dbus_xml(self) -> str:
        """Return D-Bus interface definition."""
        return f"""
        <node>
            <interface name="{self.DBUS_INTERFACE}">
                <method name="GetUserPosture">
                    <arg direction="out" type="s" name="status"/>
                    <arg direction="out" type="d" name="score"/>
                    <arg direction="out" type="d" name="tolerance"/>
                    <arg direction="out" type="d" name="alert_delay"/>
                </method>
                <method name="Recalibrate"/>
                <signal name="PostureChanged">
                    <arg type="s" name="status"/>
                    <arg type="d" name="severity"/>
                </signal>
            </interface>
        </node>
        """

    def start(self):
        """Start the posture service."""
        log(f"[posture] Starting posture monitoring service...")

        self.is_enabled = True
        self.notification_manager = NotificationManager("Praya Posture")

        # Setup D-Bus for posture-specific interface
        self.setup_dbus()
        self.register_dbus_method("GetUserPosture", self._dbus_get_user_posture)
        self.register_dbus_method("Recalibrate", self._dbus_recalibrate)

        # Initialize camera
        self.camera = CameraProcessor()
        self.camera.on_pose_detected = self._on_pose_detected
        self.camera.on_no_detection = self._on_no_detection
        self.camera.on_camera_error = self._on_camera_error

        # Start camera
        self.camera.start()

        # Try to load existing calibration data
        saved_calibration = CalibrationData.load()
        if saved_calibration and saved_calibration.is_calibrated:
            log(f"[posture] Using saved calibration data")
            self.calibration = saved_calibration
            self._set_status(PostureStatus.MONITORING)
            if self.notification_manager:
                self.notification_manager.send(
                    "Posture Monitoring Active",
                    "Using saved calibration data.",
                    urgency="low"
                )
        else:
            # No saved calibration, start calibration process
            log(f"[posture] No saved calibration, starting calibration...")
            GLib.timeout_add(1000, self._start_calibration)

        log(f"[posture] Service started")
        log(f"[posture] D-Bus: {self.DBUS_INTERFACE}")
        log(f"[posture]        Path: {self.DBUS_PATH}")

    def stop(self):
        """Stop the posture service."""
        log(f"[posture] Stopping posture monitoring service...")

        self.is_enabled = False

        # Close calibration window if open
        if self.calibration_window:
            self.calibration_window.close()
            self.calibration_window = None

        # Stop camera
        if self.camera:
            self.camera.stop()
            self.camera = None

        # Cleanup notifications
        if self.notification_manager:
            self.notification_manager.cleanup()
            self.notification_manager = None

        # Cleanup D-Bus
        self.cleanup_dbus()

        log(f"[posture] Service stopped")

    def get_status(self) -> str:
        """Get current status string."""
        return self.status.value

    def _dbus_get_user_posture(self, params, invocation):
        """Handle GetUserPosture D-Bus method."""
        result = GLib.Variant("(sddd)", (
            self.status.value,
            self.current_severity,
            self.calibration.tolerance,
            self.calibration.alert_delay
        ))
        invocation.return_value(result)

    def _dbus_recalibrate(self, params, invocation):
        """Handle Recalibrate D-Bus method."""
        GLib.idle_add(self._start_calibration)
        invocation.return_value(None)

    def _start_calibration(self) -> bool:
        """Start calibration process."""
        if not self.is_enabled:
            return False

        if self.calibration_window:
            return False

        self._set_status(PostureStatus.CALIBRATING)

        self.calibration_window = CalibrationWindow(
            self.app,
            on_complete=self._finish_calibration,
            on_cancel=self._cancel_calibration
        )
        self.calibration_window.present()

        return False

    def _finish_calibration(self, values: List[float], tolerance: float, alert_delay: float):
        """Handle calibration completion."""
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
            self.calibration.alert_delay = alert_delay
            self.calibration.is_calibrated = True

            log(f"[posture] Calibration: range={min_y:.3f}-{max_y:.3f}, tolerance={tolerance:.0%}, delay={alert_delay:.0f}s")

            # Save calibration data persistently
            self.calibration.save()

            self._set_status(PostureStatus.MONITORING)
            if self.notification_manager:
                self.notification_manager.send(
                    "Calibration Complete",
                    "Praya is now monitoring your posture.",
                    urgency="low"
                )
        else:
            self._cancel_calibration()

    def _cancel_calibration(self):
        """Handle calibration cancellation."""
        self.calibration_window = None
        self.calibration.is_calibrated = True
        self._set_status(PostureStatus.MONITORING)

    def _on_pose_detected(self, nose_y: float):
        """Handle pose detection callback."""
        if self.calibration_window:
            self.calibration_window.update_nose_y(nose_y)
            return

        if not self.is_enabled or not self.calibration.is_calibrated:
            return

        self.consecutive_no_detection = 0
        self._evaluate_posture(nose_y)

    def _on_no_detection(self):
        """Handle no detection callback."""
        self.consecutive_no_detection += 1
        self.consecutive_bad_frames = 0
        self.consecutive_good_frames = 0

        if not self.is_enabled or not self.calibration.is_calibrated:
            return

        if self.consecutive_no_detection >= self.away_frame_threshold:
            self._set_status(PostureStatus.AWAY)

    def _on_camera_error(self, error: str):
        """Handle camera error callback."""
        self._set_status(PostureStatus.CAMERA_ERROR)
        log(f"[posture] Camera error: {error}")

    def _smooth_nose_y(self, raw_y: float) -> float:
        """Smooth nose Y position using moving average."""
        self.nose_y_history.append(raw_y)
        if len(self.nose_y_history) > self.smoothing_window:
            self.nose_y_history.pop(0)
        return sum(self.nose_y_history) / len(self.nose_y_history)

    def _evaluate_posture(self, current_y: float):
        """Evaluate posture based on current nose position."""
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

                self._set_status(PostureStatus.SLOUCHING, severity)

                # Track slouch start time for delay
                if self.slouch_start_time is None:
                    self.slouch_start_time = time.time()
                    self.alert_sent_for_current_slouch = False
                    log(f"[posture] Slouching detected, waiting {self.calibration.alert_delay:.0f}s before alert...")

                # Check if delay has passed before sending notification
                elapsed = time.time() - self.slouch_start_time
                if elapsed >= self.calibration.alert_delay and not self.alert_sent_for_current_slouch:
                    if self.notification_manager:
                        self._notify_slouching(severity)
                    self.alert_sent_for_current_slouch = True
        else:
            self.consecutive_good_frames += 1
            self.consecutive_bad_frames = 0

            if self.consecutive_good_frames >= self.frame_threshold:
                # Posture is good again - reset slouch tracking
                was_slouching = self.is_currently_slouching
                if self.slouch_start_time is not None and not self.alert_sent_for_current_slouch:
                    log(f"[posture] Posture corrected before alert delay - no alert sent")
                self.is_currently_slouching = False
                self.slouch_start_time = None
                self.alert_sent_for_current_slouch = False
                self._set_status(PostureStatus.GOOD_POSTURE)

                # Notify extension that posture is good again
                if was_slouching:
                    self._notify_good_posture(normalized_slouch)

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

        # Send status to GNOME extension
        self._send_extension_status("bad", severity)

    def _notify_good_posture(self, score: float):
        """Notify extension that posture is good again."""
        self._send_extension_status("good", score)

    def _send_extension_status(self, status: str, score: float = 0.0):
        """Send posture status to GNOME extension via D-Bus."""
        log(f"[posture] Sending posture state to extension: {status}, score: {score:.2f}")
        try:
            import subprocess
            result = subprocess.run([
                "dbus-send", "--session",
                "--dest=com.github.blankon.praya",
                "/com/github/blankon/Praya",
                "com.github.blankon.Praya.PostureServiceUserStatus",
                f"string:{status}",
                f"double:{score}"
            ], capture_output=True, text=True)
            if result.returncode == 0:
                log(f"[posture] Extension notified: posture={status}, score={score:.2f}")
            else:
                log(f"[posture] Failed to notify extension: {result.stderr.strip()}")
        except Exception as e:
            log(f"[posture] Error sending to extension: {e}")

    def _set_status(self, status: PostureStatus, severity: float = 0.0):
        """Update status and emit D-Bus signal."""
        if status != self.status or (status == PostureStatus.SLOUCHING and severity != self.current_severity):
            self.status = status
            self.current_severity = severity

            if severity > 0:
                log(f"[posture] Status: {status.value} | Score: {severity:.2f}")
            else:
                log(f"[posture] Status: {status.value}")

            # Emit D-Bus signal
            self.emit_dbus_signal(
                "PostureChanged",
                GLib.Variant("(sd)", (status.value, severity))
            )
