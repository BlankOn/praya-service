#!/usr/bin/env python3
"""
Praya Service Daemon

Main daemon that listens on D-Bus and manages feature services.
Features are activated/deactivated via D-Bus commands.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio, GLib
from typing import Dict, Optional
import sys

from praya.services import AVAILABLE_SERVICES, get_service_module, get_service_description


def log(msg):
    """Print and flush immediately."""
    print(msg)
    sys.stdout.flush()


class PrayaDaemon(Adw.Application):
    """
    Main Praya daemon that manages feature services.

    D-Bus Interface: com.github.blankon.Praya
    D-Bus Path: /com/github/blankon/Praya

    Methods:
        EnableService(service_name: str) -> bool
        DisableService(service_name: str) -> bool
        ListServices() -> array of (name, description, enabled)
        GetServiceStatus(service_name: str) -> (enabled, status)

    Signals:
        ServiceStateChanged(service_name: str, enabled: bool)
    """

    APPLICATION_ID = "com.github.blankon.praya"
    DBUS_INTERFACE = "com.github.blankon.Praya"
    DBUS_PATH = "/com/github/blankon/Praya"

    DBUS_XML = """
    <node>
        <interface name="com.github.blankon.Praya">
            <method name="EnableService">
                <arg direction="in" type="s" name="service_name"/>
                <arg direction="out" type="b" name="success"/>
            </method>
            <method name="DisableService">
                <arg direction="in" type="s" name="service_name"/>
                <arg direction="out" type="b" name="success"/>
            </method>
            <method name="ListServices">
                <arg direction="out" type="a(ssb)" name="services"/>
            </method>
            <method name="GetServiceStatus">
                <arg direction="in" type="s" name="service_name"/>
                <arg direction="out" type="b" name="enabled"/>
                <arg direction="out" type="s" name="status"/>
            </method>
            <method name="Quit"/>
            <signal name="ServiceStateChanged">
                <arg type="s" name="service_name"/>
                <arg type="b" name="enabled"/>
            </signal>
        </interface>
    </node>
    """

    def __init__(self):
        super().__init__(
            application_id=self.APPLICATION_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )

        self._dbus_connection: Optional[Gio.DBusConnection] = None
        self._dbus_registration_id: Optional[int] = None
        self._bus_name_id: Optional[int] = None

        # Active service instances
        self._active_services: Dict[str, object] = {}

    def do_startup(self):
        """Setup on startup."""
        Adw.Application.do_startup(self)

    def do_activate(self):
        """Called when the daemon is activated."""
        self._setup_dbus()

        print("Praya Service Daemon")
        print("=" * 40)
        print(f"D-Bus: {self.DBUS_INTERFACE}")
        print(f"       Path: {self.DBUS_PATH}")
        print("")
        print("Available services:")
        for name in AVAILABLE_SERVICES.keys():
            print(f"  - {name}")
        print("")
        print("Waiting for D-Bus commands...")
        print("  Enable:  dbus-send --session --dest=com.github.blankon.praya \\")
        print("           /com/github/blankon/Praya com.github.blankon.Praya.EnableService \\")
        print("           string:'posture'")
        print("")
        print("  Disable: dbus-send --session --dest=com.github.blankon.praya \\")
        print("           /com/github/blankon/Praya com.github.blankon.Praya.DisableService \\")
        print("           string:'posture'")
        print("")

        self.hold()

    def _setup_dbus(self):
        """Register D-Bus service."""
        try:
            self._dbus_connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            node_info = Gio.DBusNodeInfo.new_for_xml(self.DBUS_XML)
            interface_info = node_info.interfaces[0]

            self._dbus_registration_id = self._dbus_connection.register_object(
                self.DBUS_PATH,
                interface_info,
                self._handle_method_call,
                None,
                None
            )

            # Request ownership of the bus name for D-Bus activation
            self._bus_name_id = Gio.bus_own_name_on_connection(
                self._dbus_connection,
                self.APPLICATION_ID,
                Gio.BusNameOwnerFlags.NONE,
                self._on_name_acquired,
                self._on_name_lost
            )
        except Exception as e:
            print(f"Failed to register D-Bus service: {e}")

    def _on_name_acquired(self, connection, name):
        """Called when D-Bus name is acquired."""
        print(f"D-Bus name acquired: {name}")

    def _on_name_lost(self, connection, name):
        """Called when D-Bus name is lost."""
        print(f"D-Bus name lost: {name}")

    def _handle_method_call(self, connection, sender, path, interface, method, params, invocation):
        """Handle D-Bus method calls."""
        log(f"D-Bus method called: {method}")
        try:
            if method == "EnableService":
                service_name = params.unpack()[0]
                log(f"EnableService called for: {service_name}")
                success = self._enable_service(service_name)
                log(f"EnableService result: {success}")
                invocation.return_value(GLib.Variant("(b)", (success,)))

            elif method == "DisableService":
                service_name = params.unpack()[0]
                success = self._disable_service(service_name)
                invocation.return_value(GLib.Variant("(b)", (success,)))

            elif method == "ListServices":
                services = self._list_services()
                invocation.return_value(GLib.Variant("(a(ssb))", (services,)))

            elif method == "GetServiceStatus":
                service_name = params.unpack()[0]
                enabled, status = self._get_service_status(service_name)
                invocation.return_value(GLib.Variant("(bs)", (enabled, status)))

            elif method == "Quit":
                invocation.return_value(None)
                self.quit()

            else:
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.UnknownMethod",
                    f"Unknown method: {method}"
                )
        except Exception as e:
            log(f"D-Bus method error: {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.Failed",
                str(e)
            )

    def _enable_service(self, service_name: str) -> bool:
        """Enable a service."""
        log(f"_enable_service called for: {service_name}")

        if service_name in self._active_services:
            log(f"Service '{service_name}' is already enabled")
            return True

        if service_name not in AVAILABLE_SERVICES:
            log(f"Unknown service: {service_name}")
            return False

        try:
            log(f"Enabling service: {service_name}")
            log(f"Getting module...")
            module = get_service_module(service_name)
            log(f"Module loaded: {module}")

            # Get the service class and instantiate it
            log(f"Getting service class...")
            service_class = module.get_service_class()
            log(f"Service class: {service_class}")

            log(f"Instantiating service...")
            service_instance = service_class(self)
            log(f"Service instance created: {service_instance}")

            # Start the service
            log(f"Starting service...")
            service_instance.start()
            log(f"Service started")

            self._active_services[service_name] = service_instance
            self._emit_service_state_changed(service_name, True)

            log(f"Service '{service_name}' enabled successfully")
            return True

        except Exception as e:
            log(f"Failed to enable service '{service_name}': {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            return False

    def _disable_service(self, service_name: str) -> bool:
        """Disable a service."""
        if service_name not in self._active_services:
            print(f"Service '{service_name}' is not enabled")
            return True

        try:
            print(f"Disabling service: {service_name}")
            service_instance = self._active_services[service_name]
            service_instance.stop()

            del self._active_services[service_name]
            self._emit_service_state_changed(service_name, False)

            print(f"Service '{service_name}' disabled")
            return True

        except Exception as e:
            print(f"Failed to disable service '{service_name}': {e}")
            return False

    def _list_services(self) -> list:
        """List all available services without importing service modules."""
        services = []
        for name in AVAILABLE_SERVICES:
            description = get_service_description(name)
            enabled = name in self._active_services
            services.append((name, description, enabled))

        return services

    def _get_service_status(self, service_name: str) -> tuple:
        """Get status of a service."""
        if service_name not in AVAILABLE_SERVICES:
            return (False, "unknown")

        enabled = service_name in self._active_services

        if enabled:
            service = self._active_services[service_name]
            status = service.get_status()
        else:
            status = "disabled"

        return (enabled, status)

    def _emit_service_state_changed(self, service_name: str, enabled: bool):
        """Emit ServiceStateChanged signal."""
        if self._dbus_connection:
            try:
                self._dbus_connection.emit_signal(
                    None,
                    self.DBUS_PATH,
                    self.DBUS_INTERFACE,
                    "ServiceStateChanged",
                    GLib.Variant("(sb)", (service_name, enabled))
                )
            except Exception as e:
                print(f"Failed to emit signal: {e}")

    def do_shutdown(self):
        """Cleanup on shutdown."""
        # Stop all active services
        for service_name in list(self._active_services.keys()):
            self._disable_service(service_name)

        # Release bus name
        if self._bus_name_id:
            Gio.bus_unown_name(self._bus_name_id)

        # Unregister D-Bus
        if self._dbus_connection and self._dbus_registration_id:
            self._dbus_connection.unregister_object(self._dbus_registration_id)

        Adw.Application.do_shutdown(self)


def main():
    """Entry point for praya-service command."""
    daemon = PrayaDaemon()
    return daemon.run(None)


if __name__ == "__main__":
    exit(main())
