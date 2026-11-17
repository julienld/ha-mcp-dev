"""Shared component compatibility metadata without transport imports."""

# File and YAML services require the component from the server's own release.
# semantic-release stamps this neutral contract beside the component version;
# transport adapters re-export it without introducing a Native dependency on
# the legacy filesystem tool module.
MIN_COMPONENT_VERSION = "9.2.0"
