"""Calibration UI for posture service."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

from gi.repository import Gtk, Gdk, GLib
from typing import Callable, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import sys


def log(msg):
    """Print and flush immediately."""
    print(msg)
    sys.stdout.flush()


@dataclass
class CalibrationData:
    """Stores calibration results."""
    good_posture_y: float = 0.4    # Looking up / good posture (min Y from calibration)
    bad_posture_y: float = 0.6     # Looking down / slouching (max Y from calibration)
    neutral_y: float = 0.5         # Average position
    posture_range: float = 0.2     # Range between good and bad
    tolerance: float = 0.20        # User-set tolerance (0.0 - 1.0)
    alert_delay: float = 3.0       # Seconds to wait before showing alert
    is_calibrated: bool = False

    CONFIG_DIR = Path.home() / ".config" / "praya"
    CONFIG_FILE = CONFIG_DIR / "posture_calibration.json"

    def save(self) -> bool:
        """Save calibration data to disk."""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = asdict(self)
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            log(f"[posture] Calibration data saved to {self.CONFIG_FILE}")
            return True
        except Exception as e:
            log(f"[posture] Failed to save calibration data: {e}")
            return False

    @classmethod
    def load(cls) -> Optional['CalibrationData']:
        """Load calibration data from disk. Returns None if not found."""
        try:
            if not cls.CONFIG_FILE.exists():
                log(f"[posture] No saved calibration data found")
                return None

            with open(cls.CONFIG_FILE, 'r') as f:
                data = json.load(f)

            calibration = cls(
                good_posture_y=data.get('good_posture_y', 0.4),
                bad_posture_y=data.get('bad_posture_y', 0.6),
                neutral_y=data.get('neutral_y', 0.5),
                posture_range=data.get('posture_range', 0.2),
                tolerance=data.get('tolerance', 0.20),
                alert_delay=data.get('alert_delay', 3.0),
                is_calibrated=data.get('is_calibrated', False)
            )
            log(f"[posture] Calibration data loaded from {cls.CONFIG_FILE}")
            return calibration
        except Exception as e:
            log(f"[posture] Failed to load calibration data: {e}")
            return None

    @classmethod
    def exists(cls) -> bool:
        """Check if saved calibration data exists."""
        return cls.CONFIG_FILE.exists()


class CalibrationWindow(Gtk.Window):
    """Calibration window: 4-corner calibration + tolerance slider."""

    PHASE_CORNERS = 0
    PHASE_TOLERANCE = 1

    def __init__(self, app, on_complete: Callable[[List[float], float, float], None], on_cancel: Callable[[], None]):
        super().__init__(application=app)
        self.on_complete = on_complete
        self.on_cancel = on_cancel
        self.captured_values: List[float] = []
        self.current_step = 0
        self.current_nose_y = 0.5
        self.pulse_phase = 0.0
        self.tolerance = 0.20  # Default 20%
        self.alert_delay = 3.0  # Default 3 seconds
        self.phase = self.PHASE_CORNERS

        self.steps = [
            ("Look at the TOP-LEFT corner", (0.15, 0.15)),
            ("Look at the TOP-RIGHT corner", (0.85, 0.15)),
            ("Look at the BOTTOM-RIGHT corner", (0.85, 0.85)),
            ("Look at the BOTTOM-LEFT corner", (0.15, 0.85)),
        ]

        self.set_decorated(False)
        self.set_modal(True)
        self.fullscreen()

        # Main container - will switch between drawing area and tolerance UI
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(self.main_box)

        # Phase 1: Drawing area for corner calibration
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self._on_draw)
        self.drawing_area.set_vexpand(True)
        self.drawing_area.set_hexpand(True)
        self.main_box.append(self.drawing_area)

        # Phase 2: Tolerance slider (hidden initially)
        self.tolerance_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.tolerance_box.set_valign(Gtk.Align.CENTER)
        self.tolerance_box.set_halign(Gtk.Align.CENTER)
        self.tolerance_box.set_margin_top(50)
        self.tolerance_box.set_margin_bottom(50)
        self.tolerance_box.set_margin_start(100)
        self.tolerance_box.set_margin_end(100)
        self._setup_tolerance_ui()

        # Keyboard controller
        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_controller)

        # Animation timer
        GLib.timeout_add(16, self._animate)

    def _setup_tolerance_ui(self):
        """Setup the settings UI with tolerance and delay sliders."""
        # Title
        title = Gtk.Label(label="Settings")
        title.add_css_class("title-1")
        title.set_markup("<span size='xx-large' foreground='white'>Posture Settings</span>")
        self.tolerance_box.append(title)

        # --- Tolerance Section ---
        tolerance_title = Gtk.Label()
        tolerance_title.set_markup("<span size='large' foreground='white'>Slouching Tolerance</span>")
        tolerance_title.set_margin_top(20)
        self.tolerance_box.append(tolerance_title)

        tolerance_desc = Gtk.Label()
        tolerance_desc.set_markup("<span foreground='#aaaaaa'>0 = Strict | 100 = Lenient</span>")
        self.tolerance_box.append(tolerance_desc)

        # Tolerance slider container
        tolerance_slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        tolerance_slider_box.set_halign(Gtk.Align.CENTER)

        self.tolerance_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.tolerance_slider.set_value(20)
        self.tolerance_slider.set_size_request(400, -1)
        self.tolerance_slider.connect("value-changed", self._on_tolerance_changed)
        tolerance_slider_box.append(self.tolerance_slider)

        self.tolerance_label = Gtk.Label(label="20%")
        self.tolerance_label.set_markup("<span size='large' foreground='cyan'>20%</span>")
        self.tolerance_label.set_width_chars(5)
        tolerance_slider_box.append(self.tolerance_label)

        self.tolerance_box.append(tolerance_slider_box)

        # --- Alert Delay Section ---
        delay_title = Gtk.Label()
        delay_title.set_markup("<span size='large' foreground='white'>Alert Delay</span>")
        delay_title.set_margin_top(20)
        self.tolerance_box.append(delay_title)

        delay_desc = Gtk.Label()
        delay_desc.set_markup("<span foreground='#aaaaaa'>Seconds to wait before showing alert</span>")
        self.tolerance_box.append(delay_desc)

        # Delay slider container
        delay_slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        delay_slider_box.set_halign(Gtk.Align.CENTER)

        self.delay_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        self.delay_slider.set_value(3)
        self.delay_slider.set_size_request(400, -1)
        self.delay_slider.connect("value-changed", self._on_delay_changed)
        delay_slider_box.append(self.delay_slider)

        self.delay_label = Gtk.Label(label="3s")
        self.delay_label.set_markup("<span size='large' foreground='cyan'>3s</span>")
        self.delay_label.set_width_chars(5)
        delay_slider_box.append(self.delay_label)

        self.tolerance_box.append(delay_slider_box)

        # Hint
        hint = Gtk.Label()
        hint.set_markup("<span foreground='cyan'>Press Space or Enter to start monitoring</span>")
        hint.set_margin_top(30)
        self.tolerance_box.append(hint)

        # Escape hint
        escape_hint = Gtk.Label()
        escape_hint.set_markup("<span foreground='#666666'>Press Escape to cancel</span>")
        self.tolerance_box.append(escape_hint)

    def _on_tolerance_changed(self, slider):
        """Handle tolerance slider change."""
        value = int(slider.get_value())
        self.tolerance = value / 100.0
        self.tolerance_label.set_markup(f"<span size='large' foreground='cyan'>{value}%</span>")

    def _on_delay_changed(self, slider):
        """Handle delay slider change."""
        value = int(slider.get_value())
        self.alert_delay = float(value)
        self.delay_label.set_markup(f"<span size='large' foreground='cyan'>{value}s</span>")

    def _animate(self) -> bool:
        if self.phase == self.PHASE_CORNERS:
            self.pulse_phase += 0.08
            self.drawing_area.queue_draw()
        return self.get_visible()

    def _on_draw(self, area, cr, width, height):
        import math

        # Dark background
        cr.set_source_rgba(0, 0, 0, 0.85)
        cr.paint()

        if self.phase == self.PHASE_TOLERANCE:
            return

        if self.current_step >= len(self.steps):
            return

        instruction, (rel_x, rel_y) = self.steps[self.current_step]
        target_x = width * rel_x
        target_y = height * rel_y

        base_radius = 50
        pulse_amount = 15
        radius = base_radius + math.sin(self.pulse_phase) * pulse_amount

        # Outer glow
        cr.set_source_rgba(0, 1, 1, 0.3 + 0.2 * math.sin(self.pulse_phase))
        cr.arc(target_x, target_y, radius + 25, 0, 2 * math.pi)
        cr.fill()

        # Main ring
        cr.set_source_rgba(0, 1, 1, 0.9)
        cr.set_line_width(5)
        cr.arc(target_x, target_y, radius, 0, 2 * math.pi)
        cr.stroke()

        # Center dot
        cr.set_source_rgba(1, 1, 1, 1)
        cr.arc(target_x, target_y, 10, 0, 2 * math.pi)
        cr.fill()

        # Step indicator
        cr.set_source_rgba(1, 1, 1, 0.7)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(20)
        step_text = f"Step {self.current_step + 1} of {len(self.steps)}"
        extents = cr.text_extents(step_text)
        cr.move_to((width - extents.width) / 2, 60)
        cr.show_text(step_text)

        # Instruction
        cr.set_source_rgba(1, 1, 1, 1)
        cr.set_font_size(32)
        extents = cr.text_extents(instruction)
        cr.move_to((width - extents.width) / 2, height / 2)
        cr.show_text(instruction)

        # Hint
        cr.set_source_rgba(0, 1, 1, 1)
        cr.set_font_size(18)
        hint = "Press Space when ready"
        extents = cr.text_extents(hint)
        cr.move_to((width - extents.width) / 2, height / 2 + 50)
        cr.show_text(hint)

        # Escape hint
        cr.set_source_rgba(1, 1, 1, 0.5)
        cr.set_font_size(14)
        escape_hint = "Press Escape to skip calibration"
        extents = cr.text_extents(escape_hint)
        cr.move_to((width - extents.width) / 2, height / 2 + 90)
        cr.show_text(escape_hint)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._cancel()
            return True

        if self.phase == self.PHASE_CORNERS:
            if keyval == Gdk.KEY_space:
                self._capture_position()
                return True
        elif self.phase == self.PHASE_TOLERANCE:
            if keyval in (Gdk.KEY_space, Gdk.KEY_Return):
                self._complete()
                return True
            elif keyval == Gdk.KEY_Left:
                self.tolerance_slider.set_value(max(0, self.tolerance_slider.get_value() - 5))
                return True
            elif keyval == Gdk.KEY_Right:
                self.tolerance_slider.set_value(min(100, self.tolerance_slider.get_value() + 5))
                return True

        return False

    def _capture_position(self):
        """Capture current nose position."""
        self.captured_values.append(self.current_nose_y)
        self.current_step += 1

        if self.current_step >= len(self.steps):
            self._switch_to_tolerance_phase()

    def _switch_to_tolerance_phase(self):
        """Switch to tolerance slider phase."""
        self.phase = self.PHASE_TOLERANCE
        self.main_box.remove(self.drawing_area)
        self.main_box.append(self.tolerance_box)

        # Apply dark background via CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string("window { background-color: rgba(0, 0, 0, 0.85); }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _complete(self):
        """Finish calibration."""
        self.close()
        self.on_complete(self.captured_values, self.tolerance, self.alert_delay)

    def _cancel(self):
        """Cancel calibration."""
        self.close()
        self.on_cancel()

    def update_nose_y(self, value: float):
        """Update current nose Y position from camera."""
        self.current_nose_y = value
