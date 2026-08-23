"""Compatibility facade for pointer position and display geometry."""
from __future__ import annotations

from .platform import DisplayInfo, Point, PointerBackend, select_pointer_backend
from .platform.common import locate_point


_backend: PointerBackend = select_pointer_backend()


def get_displays() -> list[DisplayInfo]:
    """Return displays from the selected platform backend."""
    _backend.initialize_coordinate_space()
    return _backend.list_displays()


def get_mouse_pos() -> Point:
    """Return the cursor position in the backend's display coordinate space."""
    _backend.initialize_coordinate_space()
    return _backend.get_cursor_position()


def locate(
    pos: Point,
    displays: list[DisplayInfo]
) -> tuple[DisplayInfo, float, float] | None:
    """Find which display contains position (in points), return pixel coordinates within display.

    Containment: origin_x <= x < origin_x + width_pts (same for y).
    Pixel scaling: (pos - origin) * (width_px / width_pts).
    Returns (display, pixel_x, pixel_y) or None if not on any display.
    """
    return locate_point(pos, displays)
