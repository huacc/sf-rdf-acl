"""Pytest configuration for end-to-end RDF tests."""
from __future__ import annotations

from pathlib import Path

from common.config import ConfigManager

# Ensure the global configuration is loaded from the repository defaults so that
# tests use the real integration endpoints declared in sf-common/config.
ConfigManager.load()

# Skip legacy unit tests that rely on stubs; only the new end-to-end suite is
# collected.
collect_ignore_glob = ["legacy/*"]
