import sys

import pytest

from obs_voice_command.platform import (
    UnsupportedPlatformError,
    select_pointer_backend,
)


def test_windows_backend_selects_without_quartz_or_win32_calls(monkeypatch):
    monkeypatch.delitem(sys.modules, "Quartz", raising=False)

    import obs_voice_command.platform.windows as windows

    load_calls = []

    def load_user32(*args, **kwargs):
        load_calls.append((args, kwargs))
        raise AssertionError("user32 must not load during backend selection")

    monkeypatch.setattr(windows.ctypes, "WinDLL", load_user32, raising=False)

    backend = select_pointer_backend("win32")

    assert type(backend).__name__ == "WindowsPointerBackend"
    assert "Quartz" not in sys.modules
    assert load_calls == []


def test_windows_backend_real_api_path_is_explicitly_unsupported_off_windows(
    monkeypatch,
):
    import obs_voice_command.platform.windows as windows

    # Simulate a non-Windows host even when this test is collected on Windows.
    monkeypatch.setattr(windows.os, "name", "posix")

    backend = select_pointer_backend("win32")

    with pytest.raises(UnsupportedPlatformError, match="only available on Windows"):
        backend.list_displays()


def test_unsupported_backend_imports_safely(monkeypatch):
    monkeypatch.delitem(sys.modules, "Quartz", raising=False)

    backend = select_pointer_backend("linux")

    assert type(backend).__name__ == "UnsupportedPointerBackend"
    backend.initialize_coordinate_space()
    with pytest.raises(UnsupportedPlatformError, match="linux"):
        backend.get_cursor_position()
    assert "Quartz" not in sys.modules
