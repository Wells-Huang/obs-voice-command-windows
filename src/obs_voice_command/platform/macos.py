"""Quartz pointer and display adapter for macOS."""
from __future__ import annotations

import Quartz

from .common import DisplayInfo, Point


class MacOSPointerBackend:
    """Read Quartz display geometry and cursor position."""

    def initialize_coordinate_space(self) -> None:
        """Quartz already exposes a process-wide global coordinate space."""

    def list_displays(self) -> list[DisplayInfo]:
        _error, display_ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
        displays = []
        for display_id in display_ids[:count]:
            bounds = Quartz.CGDisplayBounds(display_id)
            displays.append(
                DisplayInfo(
                    origin_x=float(bounds.origin.x),
                    origin_y=float(bounds.origin.y),
                    width_pts=float(bounds.size.width),
                    height_pts=float(bounds.size.height),
                    width_px=int(Quartz.CGDisplayPixelsWide(display_id)),
                    height_px=int(Quartz.CGDisplayPixelsHigh(display_id)),
                    id=f"quartz:{display_id}",
                    aliases=(str(display_id),),
                    primary=bool(Quartz.CGDisplayIsMain(display_id)),
                    metadata={"quartz_display_id": display_id},
                )
            )
        return displays

    def get_cursor_position(self) -> Point:
        event = Quartz.CGEventCreate(None)
        location = Quartz.CGEventGetLocation(event)
        return float(location.x), float(location.y)
