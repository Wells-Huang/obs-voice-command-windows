import importlib
import sys
from types import ModuleType, SimpleNamespace


def _fake_quartz_for_pointer():
    quartz = ModuleType("Quartz")
    quartz.CGGetActiveDisplayList = lambda limit, active, count: (0, [10, 20], 2)
    quartz.CGDisplayBounds = lambda display_id: SimpleNamespace(
        origin=SimpleNamespace(x=0 if display_id == 10 else 1512, y=0),
        size=SimpleNamespace(width=1512 if display_id == 10 else 1920, height=982),
    )
    quartz.CGDisplayPixelsWide = lambda display_id: 3024 if display_id == 10 else 1920
    quartz.CGDisplayPixelsHigh = lambda display_id: 1964 if display_id == 10 else 982
    quartz.CGDisplayIsMain = lambda display_id: display_id == 10
    quartz.CGEventCreate = lambda source: object()
    quartz.CGEventGetLocation = lambda event: SimpleNamespace(x=101.5, y=202.25)
    return quartz


def test_macos_pointer_adapter_preserves_quartz_behavior(monkeypatch):
    module_name = "obs_voice_command.platform.macos"
    sys.modules.pop(module_name, None)
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz_for_pointer())
    module = importlib.import_module(module_name)

    backend = module.MacOSPointerBackend()
    displays = backend.list_displays()

    assert [(item.width_pts, item.width_px) for item in displays] == [
        (1512.0, 3024),
        (1920.0, 1920),
    ]
    assert displays[0].id == "quartz:10"
    assert displays[0].primary is True
    assert displays[1].origin_x == 1512.0
    assert backend.get_cursor_position() == (101.5, 202.25)

    sys.modules.pop(module_name, None)
