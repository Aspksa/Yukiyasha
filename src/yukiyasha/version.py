"""Canonical application version helpers."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed Yukiyasha package version."""
    try:
        return version("yukiyasha")
    except PackageNotFoundError:
        return "0.0.0+dev"
