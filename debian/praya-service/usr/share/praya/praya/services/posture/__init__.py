"""
Praya Posture Service - Posture monitoring using camera and pose detection.

This service monitors your posture via webcam and sends notifications
when slouching is detected.
"""

from .service import PostureService

__all__ = ['PostureService']


def get_service_class():
    """Return the service class for this feature."""
    return PostureService


def get_service_description():
    """Return a description of this service."""
    return "Posture monitoring using camera and pose detection"


def main():
    """Entry point for standalone praya-posture command."""
    from praya.daemon import PrayaDaemon

    # Create a minimal daemon that auto-enables posture
    class PostureOnlyDaemon(PrayaDaemon):
        def do_activate(self):
            super().do_activate()
            # Auto-enable posture service
            self._enable_service("posture")

    daemon = PostureOnlyDaemon()
    return daemon.run(None)
