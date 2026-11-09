"""Orkestra: budget-aware task dispatcher for multiple AIs under one chief."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("orkestra-cli")  # single source: pyproject.toml
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
