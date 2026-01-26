"""D-Bus utilities for Praya services."""

from gi.repository import Gio, GLib
from typing import Optional, Callable


class DBusServiceMixin:
    """
    Mixin class providing D-Bus functionality for services.

    Usage:
        class MyService(BaseService, DBusServiceMixin):
            DBUS_INTERFACE = "com.github.Praya.MyService"
            DBUS_PATH = "/com/github/Praya/MyService"

            def __init__(self):
                super().__init__()
                self.setup_dbus(self.get_dbus_xml())
    """

    DBUS_INTERFACE: str = "com.github.Praya.Base"
    DBUS_PATH: str = "/com/github/Praya/Base"

    def __init__(self):
        self._dbus_connection: Optional[Gio.DBusConnection] = None
        self._dbus_registration_id: Optional[int] = None
        self._dbus_method_handlers: dict = {}

    def get_dbus_xml(self) -> str:
        """
        Return D-Bus interface XML. Override in subclasses.

        Example:
            return '''
            <node>
                <interface name="com.github.Praya.MyService">
                    <method name="GetStatus">
                        <arg direction="out" type="s" name="status"/>
                    </method>
                    <signal name="StatusChanged">
                        <arg type="s" name="status"/>
                    </signal>
                </interface>
            </node>
            '''
        """
        return f"""
        <node>
            <interface name="{self.DBUS_INTERFACE}">
                <method name="GetStatus">
                    <arg direction="out" type="s" name="status"/>
                </method>
            </interface>
        </node>
        """

    def setup_dbus(self, xml: Optional[str] = None):
        """Register D-Bus service."""
        try:
            self._dbus_connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            node_info = Gio.DBusNodeInfo.new_for_xml(xml or self.get_dbus_xml())
            interface_info = node_info.interfaces[0]

            self._dbus_registration_id = self._dbus_connection.register_object(
                self.DBUS_PATH,
                interface_info,
                self._handle_dbus_method_call,
                None,
                None
            )
            print(f"D-Bus service registered: {self.DBUS_INTERFACE}")
            print(f"       Path: {self.DBUS_PATH}")
        except Exception as e:
            print(f"Failed to register D-Bus service: {e}")

    def _handle_dbus_method_call(self, connection, sender, path, interface, method, params, invocation):
        """Handle D-Bus method calls. Override for custom handling."""
        handler = self._dbus_method_handlers.get(method)
        if handler:
            handler(params, invocation)
        elif method == "GetStatus":
            status = getattr(self, 'status', None)
            status_str = status.value if status else "unknown"
            invocation.return_value(GLib.Variant("(s)", (status_str,)))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method}"
            )

    def register_dbus_method(self, method_name: str, handler: Callable):
        """Register a handler for a D-Bus method."""
        self._dbus_method_handlers[method_name] = handler

    def emit_dbus_signal(self, signal_name: str, parameters: GLib.Variant):
        """Emit a D-Bus signal."""
        if self._dbus_connection:
            try:
                self._dbus_connection.emit_signal(
                    None,  # destination (None = broadcast)
                    self.DBUS_PATH,
                    self.DBUS_INTERFACE,
                    signal_name,
                    parameters
                )
            except Exception as e:
                print(f"Failed to emit D-Bus signal: {e}")

    def cleanup_dbus(self):
        """Unregister D-Bus service."""
        if self._dbus_connection and self._dbus_registration_id:
            self._dbus_connection.unregister_object(self._dbus_registration_id)
