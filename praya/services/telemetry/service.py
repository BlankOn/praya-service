"""Telemetry service - sends daily device information to the tracker."""

import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from gi.repository import GLib

from praya.core import DBusServiceMixin


def log(msg):
    """Print and flush immediately."""
    print(msg)
    sys.stdout.flush()


TELEMETRY_URL = "https://telemetry.blankonlinux.id/events"
CONFIG_DIR = Path.home() / ".config" / "praya"
CONFIG_FILE = CONFIG_DIR / "telemetry.json"


class TelemetryService(DBusServiceMixin):
    """
    Telemetry service that sends daily device information.

    Collects CPU, memory, and disk specs, generates a persistent device ID,
    and sends a single "daily" event per day to the BlankOn telemetry endpoint.
    """

    SERVICE_NAME = "telemetry"
    SERVICE_DESCRIPTION = "Daily device telemetry reporting"
    DBUS_INTERFACE = "com.github.blankon.Praya.Telemetry"
    DBUS_PATH = "/com/github/blankon/Praya/Telemetry"

    def __init__(self, app):
        DBusServiceMixin.__init__(self)
        self.app = app
        self.is_enabled = False
        self.status = "disabled"
        self._timer_id: Optional[int] = None
        self._config = self._load_config()

    def get_dbus_xml(self) -> str:
        return f"""
        <node>
            <interface name="{self.DBUS_INTERFACE}">
                <method name="GetStatus">
                    <arg direction="out" type="s" name="status"/>
                </method>
            </interface>
        </node>
        """

    def start(self):
        """Start the telemetry service."""
        log("[telemetry] Starting telemetry service...")

        self.is_enabled = True
        self.status = "running"

        self.setup_dbus()

        # Send enable event, then start daily check
        self._send_event_sync("enable_telemetry")

        # Try to send daily immediately, then check every hour
        GLib.idle_add(self._try_send_daily)
        self._timer_id = GLib.timeout_add_seconds(3600, self._try_send_daily)

        log(f"[telemetry] Service started")
        log(f"[telemetry] D-Bus: {self.DBUS_INTERFACE}")
        log(f"[telemetry]        Path: {self.DBUS_PATH}")
        log(f"[telemetry] Device ID: {self._config['device_id']}")

    def stop(self):
        """Stop the telemetry service."""
        log("[telemetry] Stopping telemetry service...")

        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

        # Send disable event before shutting down
        self._send_event_sync("disable_telemetry")

        self.is_enabled = False
        self.status = "disabled"

        self.cleanup_dbus()

        log("[telemetry] Service stopped")

    def get_status(self) -> str:
        return self.status

    # -- Config persistence --

    def _load_config(self) -> dict:
        """Load or initialize telemetry config with persistent device ID."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                if "device_id" in config:
                    return config
            except (json.JSONDecodeError, OSError) as e:
                log(f"[telemetry] Failed to load config: {e}")

        config = {
            "device_id": str(uuid.uuid4()),
            "last_sent_date": None,
        }
        self._save_config(config)
        return config

    def _save_config(self, config: dict):
        """Persist config to disk."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            log(f"[telemetry] Failed to save config: {e}")

    # -- Daily send logic --

    def _try_send_daily(self) -> bool:
        """Check if we need to send today's event, then send in background."""
        if not self.is_enabled:
            return False

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._config.get("last_sent_date") == today:
            log(f"[telemetry] Already sent today ({today}), skipping")
            return True  # Keep the timer alive

        log(f"[telemetry] Sending daily telemetry for {today}...")
        thread = Thread(target=self._send_event, args=("daily", True), daemon=True)
        thread.start()
        return True  # Keep the timer alive

    def _send_event_sync(self, event_name: str):
        """Send an event synchronously (blocks until done or timeout)."""
        done = Event()

        def _do_send():
            self._send_event(event_name)
            done.set()

        thread = Thread(target=_do_send, daemon=True)
        thread.start()
        done.wait(timeout=30)

    def _send_event(self, event_name: str, update_last_sent: bool = False):
        """Send an event to the telemetry endpoint (runs in background thread)."""
        payload = self._collect_device_info()
        payload["device_id"] = self._config["device_id"]

        event = {
            "event_name": event_name,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "payload": payload,
        }

        try:
            data = json.dumps(event).encode("utf-8")
            req = Request(
                TELEMETRY_URL,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                log(f"[telemetry] Event '{event_name}' sent successfully (HTTP {resp.status})")

            if update_last_sent:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self._config["last_sent_date"] = today
                self._save_config(self._config)

        except (URLError, OSError) as e:
            log(f"[telemetry] Failed to send event '{event_name}': {e}")

    # -- Device info collection --

    def _collect_device_info(self) -> dict:
        """Collect device hardware and OS information."""
        info = {
            "os": platform.system().lower(),
            "os_release": self._read_os_release(),
            "kernel": platform.release(),
            "arch": platform.machine(),
            "cpu": self._get_cpu_info(),
            "memory_mb": self._get_memory_mb(),
            "disk": self._get_disk_info(),
        }
        return info

    def _read_os_release(self) -> str:
        """Read PRETTY_NAME from /etc/os-release."""
        try:
            with open("/etc/os-release", "r") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return platform.platform()

    def _get_cpu_info(self) -> dict:
        """Get CPU model and core count."""
        model = ""
        cores = os.cpu_count() or 0

        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        model = line.split(":", 1)[1].strip()
                        break
        except OSError:
            model = platform.processor()

        return {"model": model, "cores": cores}

    def _get_memory_mb(self) -> int:
        """Get total memory in MB from /proc/meminfo."""
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb // 1024
        except (OSError, ValueError, IndexError):
            pass
        return 0

    def _get_disk_info(self) -> list:
        """Get disk device models and sizes."""
        disks = []
        block_dir = Path("/sys/block")
        if not block_dir.exists():
            return disks

        for dev in sorted(block_dir.iterdir()):
            name = dev.name
            # Skip virtual devices (loop, ram, dm-, etc.)
            if name.startswith(("loop", "ram", "dm-", "zram")):
                continue

            size_path = dev / "size"
            model_path = dev / "device" / "model"

            try:
                sectors = int(size_path.read_text().strip())
                size_gb = round((sectors * 512) / (1024 ** 3), 1)
                if size_gb == 0:
                    continue
            except (OSError, ValueError):
                continue

            model = ""
            try:
                model = model_path.read_text().strip()
            except OSError:
                pass

            disks.append({"device": name, "model": model, "size_gb": size_gb})

        return disks
