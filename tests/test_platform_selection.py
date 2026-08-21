import sys

import pytest

from obs_voice_command.platform import (
    UnsupportedPlatformError,
    select_pointer_backend,
)


def test_windows_backend_selects_without_quartz_or_win32_calls(monkeypatch):
    monkeypatch.delitem(sys.modules, "Quartz", raising=False)

    backend = select_pointer_backend("win32")

    assert type(backend).__name__ == "WindowsPointerBackend"
    assert "Quartz" not in sys.modules
    with pytest.raises(UnsupportedPlatformError, match="pending W11-003"):
        backend.list_displays()


def test_unsupported_backend_imports_safely(monkeypatch):
    monkeypatch.delitem(sys.modules, "Quartz", raising=False)

    backend = select_pointer_backend("linux")

    assert type(backend).__name__ == "UnsupportedPointerBackend"
    backend.initialize_coordinate_space()
    with pytest.raises(UnsupportedPlatformError, match="linux"):
        backend.get_cursor_position()
    assert "Quartz" not in sys.modules
