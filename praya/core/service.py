"""Base service class for Praya services."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio, GLib
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class ServiceStatus(Enum):
    """Generic service status."""
    STARTING = "Starting..."
    RUNNING = "Running"
    PAUSED = "Paused"
    DISABLED = "Disabled"
    ERROR = "Error"


class BaseService(Adw.Application):
    """
    Base class for all Praya services.

    Each service should:
    1. Inherit from BaseService
    2. Implement do_activate() to start the service logic
    3. Implement do_shutdown() to clean up resources
    4. Optionally override _setup_actions() for custom actions
    """

    # Subclasses should override these
    SERVICE_NAME = "base"
    SERVICE_DESCRIPTION = "Base Praya Service"
    APPLICATION_ID = "com.github.praya.base"
    DBUS_INTERFACE = "com.github.Praya.Base"
    DBUS_PATH = "/com/github/Praya/Base"

    def __init__(self, application_id: Optional[str] = None):
        super().__init__(
            application_id=application_id or self.APPLICATION_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.status = ServiceStatus.STARTING
        self.is_enabled = True

    def do_startup(self):
        """Setup actions on startup."""
        Adw.Application.do_startup(self)
        self._setup_actions()

    def _setup_actions(self):
        """Setup application actions. Override in subclasses for custom actions."""
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda a, p: self.quit())
        self.add_action(quit_action)

    def set_status(self, status: ServiceStatus):
        """Update service status."""
        if status != self.status:
            self.status = status
            self.on_status_changed(status)

    def on_status_changed(self, status: ServiceStatus):
        """Called when status changes. Override in subclasses."""
        print(f"[{self.SERVICE_NAME}] Status: {status.value}")

    def toggle_enabled(self, enabled: bool):
        """Enable or disable the service."""
        self.is_enabled = enabled
        if not self.is_enabled:
            self.set_status(ServiceStatus.DISABLED)
        else:
            self.set_status(ServiceStatus.RUNNING)

    @classmethod
    def get_service_info(cls) -> dict:
        """Return service metadata."""
        return {
            "name": cls.SERVICE_NAME,
            "description": cls.SERVICE_DESCRIPTION,
            "application_id": cls.APPLICATION_ID,
            "dbus_interface": cls.DBUS_INTERFACE,
            "dbus_path": cls.DBUS_PATH,
        }
