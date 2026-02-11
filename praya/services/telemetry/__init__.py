"""
Praya Telemetry Service - Sends daily device telemetry to the tracker service.

This service collects device information (CPU, memory, disk) and sends
a single "daily" event per day to the BlankOn telemetry endpoint.
"""

from .service import TelemetryService

__all__ = ['TelemetryService']


def get_service_class():
    """Return the service class for this feature."""
    return TelemetryService


def get_service_description():
    """Return a description of this service."""
    return "Daily device telemetry reporting"
