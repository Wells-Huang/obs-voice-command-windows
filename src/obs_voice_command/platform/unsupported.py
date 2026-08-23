"""Safe placeholder backend for platforms without pointer support."""
from __future__ import annotations

from .common import DisplayInfo, Point


class UnsupportedPlatformError(RuntimeError):
    """Raised when a requested platform capability is unavailable."""


class UnsupportedPointerBackend:
    """Import-safe backend that fails only when pointer APIs are used."""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    def initialize_coordinate_space(self) -> None:
        """No process coordinate initialization is available."""

    def _raise(self) -> None:
        raise UnsupportedPlatformError(
            f"pointer/display support is unavailable on {self.platform_name!r}"
        )

    def list_displays(self) -> list[DisplayInfo]:
        self._raise()

    def get_cursor_position(self) -> Point:
        self._raise()
