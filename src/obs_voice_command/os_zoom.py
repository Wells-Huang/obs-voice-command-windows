"""Import-safe compatibility facade for the macOS Accessibility Zoom helper."""
from __future__ import annotations

import sys
from types import ModuleType

from .platform import UnsupportedPlatformError


def _macos_adapter() -> ModuleType:
    if sys.platform != "darwin":
        raise UnsupportedPlatformError(
            f"OS zoom is available only on macOS; current platform is {sys.platform!r}"
        )

    # Quartz remains lazy so importing the CLI is safe on every platform.
    from .platform import macos_os_zoom

    return macos_os_zoom


def is_zoomed() -> bool:
    """Return whether macOS Accessibility Zoom is currently active."""
    return _macos_adapter().is_zoomed()


def zoom_in(target: float = 1.5) -> None:
    """Zoom in through the existing macOS Accessibility Zoom behavior."""
    _macos_adapter().zoom_in(target=target)


def zoom_out() -> None:
    """Zoom out through the existing macOS Accessibility Zoom behavior."""
    _macos_adapter().zoom_out()
