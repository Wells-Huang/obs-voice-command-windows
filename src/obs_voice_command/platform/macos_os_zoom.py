"""Quartz implementation of macOS Accessibility Zoom."""
from __future__ import annotations

import subprocess
import time

import Quartz


_KEY_TOGGLE = 28  # kVK_ANSI_8
_CMD_OPT = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate
_DOMAIN = "com.apple.universalaccess"


def _key(code: int) -> None:
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, _CMD_OPT)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.05)


def _read(key: str, default: float = 0.0) -> float:
    result = subprocess.run(
        ["defaults", "read", _DOMAIN, key], capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return default


def is_zoomed() -> bool:
    return _read("closeViewZoomedIn") >= 1.0


def zoom_in(target: float = 1.5) -> None:
    """Set the near point and toggle smoothly to the target zoom."""
    if is_zoomed():
        return
    for key in ("closeViewNearPoint", "closeViewDesiredZoomFactor"):
        subprocess.run(["defaults", "write", _DOMAIN, key, "-float", str(target)])
    time.sleep(0.2)
    _key(_KEY_TOGGLE)


def zoom_out() -> None:
    """Toggle smoothly to 1x when Accessibility Zoom is active."""
    if is_zoomed():
        _key(_KEY_TOGGLE)
