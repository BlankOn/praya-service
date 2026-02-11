"""Praya services package."""

# Service registry - add new services here
AVAILABLE_SERVICES = {
    "posture": "praya.services.posture",
    "telemetry": "praya.services.telemetry",
}


def get_service_module(service_name: str):
    """Get a service module by name."""
    if service_name not in AVAILABLE_SERVICES:
        raise ValueError(f"Unknown service: {service_name}")

    module_path = AVAILABLE_SERVICES[service_name]
    import importlib
    return importlib.import_module(module_path)


def list_services() -> list:
    """List all available services."""
    return list(AVAILABLE_SERVICES.keys())
