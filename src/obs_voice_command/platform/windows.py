"""Import-safe Windows pointer backend placeholder owned by W11-002."""
from __future__ import annotations

from .unsupported import UnsupportedPointerBackend


class WindowsPointerBackend(UnsupportedPointerBackend):
    """Placeholder until W11-003 implements the real Win32 backend."""

    def __init__(self) -> None:
        super().__init__("win32 (backend pending W11-003)")
