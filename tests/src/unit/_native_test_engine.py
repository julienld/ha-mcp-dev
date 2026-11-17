"""Build the public shared engine over a real Native backend."""

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.runtime import Engine
from ha_mcp.runtime.catalog import build_initial_catalog


def native_engine(backend: NativeBackend, names: set[str] | None = None) -> Engine:
    definitions = build_initial_catalog(backend)
    if names is not None:
        definitions = [
            definition for definition in definitions if definition.name in names
        ]
    return Engine(backend, definitions)
