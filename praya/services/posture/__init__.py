"""
Praya Posture Service - Posture monitoring using camera and pose detection.

This service monitors your posture via webcam and sends notifications
when slouching is detected.
"""

from .service import PostureService

__all__ = ['PostureService']


def main():
    """Entry point for praya-posture command."""
    service = PostureService()
    return service.run(None)
