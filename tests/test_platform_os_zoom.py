import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from obs_voice_command import os_zoom
from obs_voice_command.platform import UnsupportedPlatformError


def _fake_quartz_for_zoom(events):
    quartz = ModuleType("Quartz")
    quartz.kCGEventFlagMaskCommand = 1
    quartz.kCGEventFlagMaskAlternate = 2
    quartz.kCGHIDEventTap = 3
    quartz.CGEventCreateKeyboardEvent = lambda source, code, down: (code, down)
    quartz.CGEventSetFlags = lambda event, flags: events.append(("flags", event, flags))
    quartz.CGEventPost = lambda tap, event: events.append(("post", tap, event))
    return quartz


def test_os_zoom_facade_is_unsupported_without_loading_quartz(monkeypatch):
    monkeypatch.setattr(os_zoom.sys, "platform", "win32")
    monkeypatch.delitem(sys.modules, "Quartz", raising=False)

    with pytest.raises(UnsupportedPlatformError, match="only on macOS"):
        os_zoom.zoom_in()

    assert "Quartz" not in sys.modules


def test_macos_os_zoom_adapter_keeps_toggle_behavior(monkeypatch):
    module_name = "obs_voice_command.platform.macos_os_zoom"
    events = []
    commands = []
    sys.modules.pop(module_name, None)
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_for_zoom(events))
    module = importlib.import_module(module_name)

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout="0\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    module.zoom_in(target=2.0)

    assert commands == [
        ["defaults", "read", "com.apple.universalaccess", "closeViewZoomedIn"],
        [
            "defaults",
            "write",
            "com.apple.universalaccess",
            "closeViewNearPoint",
            "-float",
            "2.0",
        ],
        [
            "defaults",
            "write",
            "com.apple.universalaccess",
            "closeViewDesiredZoomFactor",
            "-float",
            "2.0",
        ],
    ]
    assert events == [
        ("flags", (28, True), 3),
        ("post", 3, (28, True)),
        ("flags", (28, False), 3),
        ("post", 3, (28, False)),
    ]

    sys.modules.pop(module_name, None)


def test_os_zoom_public_facade_delegates_to_macos_adapter(monkeypatch):
    calls = []
    adapter = SimpleNamespace(
        is_zoomed=lambda: True,
        zoom_in=lambda target: calls.append(("in", target)),
        zoom_out=lambda: calls.append(("out",)),
    )
    monkeypatch.setattr(os_zoom, "_macos_adapter", lambda: adapter)

    assert os_zoom.is_zoomed() is True
    os_zoom.zoom_in(target=1.75)
    os_zoom.zoom_out()

    assert calls == [("in", 1.75), ("out",)]
