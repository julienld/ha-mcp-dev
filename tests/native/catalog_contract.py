"""Schema comparison shared by static catalogue and live upgrade qualification."""

from typing import Any

_DOCUMENTATION = frozenset({"title", "description", "examples", "$comment"})
_NAME_MAPS = frozenset(
    {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
)
_OPAQUE_VALUES = frozenset({"default", "const", "enum", "example", "examples"})


def structural_schema(value: Any) -> Any:
    """Ignore prose, preserving user keys and literal values named like prose."""
    if isinstance(value, list):
        return [structural_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in _DOCUMENTATION:
            continue
        if key in _NAME_MAPS and isinstance(item, dict):
            result[key] = {
                name: structural_schema(schema) for name, schema in item.items()
            }
        elif key in _OPAQUE_VALUES or key.startswith("x-"):
            result[key] = item
        else:
            result[key] = structural_schema(item)
    return result
