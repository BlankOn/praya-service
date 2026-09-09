"""Praya services package."""

# Service registry - module path + static description to avoid eager imports
AVAILABLE_SERVICES = {
    "posture": {
        "module": "praya.services.posture",
        "description": "Posture monitoring using camera and pose detection",
    },
}


def get_service_module(service_name: str):
    """Get a service module by name (lazy import)."""
    if service_name not in AVAILABLE_SERVICES:
        raise ValueError(f"Unknown service: {service_name}")

    module_path = AVAILABLE_SERVICES[service_name]["module"]
    import importlib
    return importlib.import_module(module_path)


def get_service_description(service_name: str) -> str:
    """Get service description without importing the module."""
    if service_name not in AVAILABLE_SERVICES:
        return "Unknown"
    return AVAILABLE_SERVICES[service_name]["description"]


def list_services() -> list:
    """List all available services."""
    return list(AVAILABLE_SERVICES.keys())
