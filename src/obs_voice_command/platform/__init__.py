"""Platform selection for pointer and display backends."""
from __future__ import annotations

import sys

from .common import DisplayInfo, Point, PointerBackend, point_to_display_pixels
from .unsupported import UnsupportedPlatformError, UnsupportedPointerBackend


def select_pointer_backend(platform_name: str | None = None) -> PointerBackend:
    """Select a backend without importing adapters for other platforms."""
    selected = sys.platform if platform_name is None else platform_name

    if selected == "darwin":
        from .macos import MacOSPointerBackend

        return MacOSPointerBackend()

    if selected == "win32":
        from .windows import WindowsPointerBackend

        return WindowsPointerBackend()

    return UnsupportedPointerBackend(selected)


__all__ = [
    "DisplayInfo",
    "Point",
    "PointerBackend",
    "UnsupportedPlatformError",
    "UnsupportedPointerBackend",
    "point_to_display_pixels",
    "select_pointer_backend",
]
