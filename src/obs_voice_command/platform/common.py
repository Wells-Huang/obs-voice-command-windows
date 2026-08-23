"""Platform-neutral pointer and display contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, TypeAlias, runtime_checkable


Point: TypeAlias = tuple[float, float]


@dataclass(frozen=True)
class DisplayInfo:
    """A display rectangle and its mapping to source pixels.

    ``origin_*`` and ``*_pts`` describe the coordinate space used by the
    backend's cursor API. For Win32 that space is physical pixels; for Quartz
    it is the global point coordinate space. ``*_px`` is always the display's
    physical pixel extent.
    """

    origin_x: float
    origin_y: float
    width_pts: float
    height_pts: float
    width_px: int
    height_px: int
    id: str = ""
    aliases: tuple[str, ...] = ()
    primary: bool = False
    metadata: Mapping[str, Any] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.width_pts <= 0 or self.height_pts <= 0:
            raise ValueError("display coordinate dimensions must be positive")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("display pixel dimensions must be positive")
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def contains(self, point: Point) -> bool:
        """Return whether a point is inside this half-open display rectangle."""
        x, y = point
        return (
            self.origin_x <= x < self.origin_x + self.width_pts
            and self.origin_y <= y < self.origin_y + self.height_pts
        )


def point_to_display_pixels(point: Point, display: DisplayInfo) -> Point:
    """Convert a point in backend coordinates to pixels relative to a display."""
    x, y = point
    rel_x = x - display.origin_x
    rel_y = y - display.origin_y
    return (
        rel_x * display.width_px / display.width_pts,
        rel_y * display.height_px / display.height_pts,
    )


def locate_point(
    point: Point, displays: list[DisplayInfo]
) -> tuple[DisplayInfo, float, float] | None:
    """Locate a point and return its display-relative physical pixels."""
    for display in displays:
        if display.contains(point):
            pixel_x, pixel_y = point_to_display_pixels(point, display)
            return display, pixel_x, pixel_y
    return None


@runtime_checkable
class PointerBackend(Protocol):
    """Backend interface shared by macOS, Windows, and unsupported platforms."""

    def initialize_coordinate_space(self) -> None:
        """Initialize the process coordinate space before any pointer query."""

    def list_displays(self) -> list[DisplayInfo]:
        """Return active displays in the cursor API's coordinate space."""

    def get_cursor_position(self) -> Point:
        """Return the cursor position in the display coordinate space."""
