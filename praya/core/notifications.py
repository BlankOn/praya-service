"""Notification utilities for Praya services."""

import gi
gi.require_version('Notify', '0.7')

from gi.repository import Notify
import time
from typing import Optional


class NotificationManager:
    """
    Manages desktop notifications via libnotify.

    Usage:
        notifications = NotificationManager("MyService")
        notifications.send("Title", "Body", urgency="normal")
    """

    def __init__(self, app_name: str, cooldown: float = 5.0):
        """
        Initialize notification manager.

        Args:
            app_name: Application name shown in notifications
            cooldown: Minimum seconds between notifications
        """
        self.app_name = app_name
        self.cooldown = cooldown
        self.last_notification_time = 0
        self.current_notification: Optional[Notify.Notification] = None

        # Initialize libnotify
        if not Notify.is_initted():
            Notify.init(app_name)

    def send(self, title: str, body: str, icon: str = "dialog-information",
             urgency: str = "normal", force: bool = False):
        """
        Send a desktop notification.

        Args:
            title: Notification title
            body: Notification body text
            icon: Icon name (default: dialog-information)
            urgency: "low", "normal", or "critical"
            force: If True, ignore cooldown
        """
        current_time = time.time()

        # Rate limit notifications unless forced
        if not force and (current_time - self.last_notification_time) < self.cooldown:
            return

        self.last_notification_time = current_time

        # Create or update notification
        if self.current_notification:
            self.current_notification.update(title, body, icon)
        else:
            self.current_notification = Notify.Notification.new(title, body, icon)

        # Set urgency
        urgency_map = {
            "low": Notify.Urgency.LOW,
            "normal": Notify.Urgency.NORMAL,
            "critical": Notify.Urgency.CRITICAL,
        }
        self.current_notification.set_urgency(urgency_map.get(urgency, Notify.Urgency.NORMAL))

        # Show the notification
        try:
            self.current_notification.show()
        except Exception as e:
            print(f"Failed to show notification: {e}")

    def close(self):
        """Close any active notification."""
        if self.current_notification:
            try:
                self.current_notification.close()
            except Exception:
                pass

    def cleanup(self):
        """Clean up notification resources."""
        self.close()
        if Notify.is_initted():
            Notify.uninit()
