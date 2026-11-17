"""Load the real Native backend module for tests of its public ports."""

import importlib
from types import ModuleType

import pytest


@pytest.fixture
def native() -> ModuleType:
    return importlib.import_module("custom_components.ha_mcp_tools.native_backend")
