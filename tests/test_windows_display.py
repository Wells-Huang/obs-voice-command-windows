import ctypes
from types import SimpleNamespace

import pytest

import obs_voice_command.platform.windows as windows


class FakePointerApi:
    def __init__(
        self,
        *,
        set_result=True,
        last_error=0,
        current_awareness=windows.DPI_AWARENESS_PER_MONITOR_AWARE,
        displays=(),
        cursor=(0.0, 0.0),
    ):
        self.set_result = set_result
        self.last_error = last_error
        self.current_awareness = current_awareness
        self.displays = list(displays)
        self.cursor = cursor
        self.set_calls = []
        self.current_awareness_calls = 0
        self.display_calls = 0
        self.cursor_calls = 0

    def set_process_dpi_awareness_context(self, context):
        self.set_calls.append(context)
        return self.set_result

    def get_last_error(self):
        return self.last_error

    def get_current_dpi_awareness(self):
        self.current_awareness_calls += 1
        return self.current_awareness

    def enumerate_monitors(self):
        self.display_calls += 1
        return self.displays

    def get_cursor_position(self):
        self.cursor_calls += 1
        return self.cursor


def _record(
    left,
    top,
    right,
    bottom,
    device_name,
    interface_id,
    primary,
):
    return SimpleNamespace(
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        device_name=device_name,
        interface_id=interface_id,
        primary=primary,
    )


def test_backend_construction_is_lazy(monkeypatch):
    load_calls = []

    def load_user32(*args, **kwargs):
        load_calls.append((args, kwargs))
        raise AssertionError("user32 must not load during construction")

    monkeypatch.setattr(windows.ctypes, "WinDLL", load_user32, raising=False)

    backend = windows.WindowsPointerBackend()

    assert backend._coordinate_space_initialized is False
    assert load_calls == []


def test_dpi_awareness_is_requested_before_display_query():
    api = FakePointerApi(
        displays=[
            _record(0, 0, 1920, 1080, r"\\.\DISPLAY1", "monitor-1", True)
        ]
    )

    displays = windows.WindowsPointerBackend(api).list_displays()

    assert api.set_calls == [windows.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2]
    assert api.display_calls == 1
    assert displays[0].id == "monitor-1"


def test_already_set_dpi_awareness_is_accepted_only_when_compatible():
    api = FakePointerApi(
        set_result=False,
        last_error=windows.ERROR_ACCESS_DENIED,
        current_awareness=windows.DPI_AWARENESS_PER_MONITOR_AWARE,
        cursor=(-10.0, 20.0),
    )

    assert windows.WindowsPointerBackend(api).get_cursor_position() == (-10.0, 20.0)
    assert api.current_awareness_calls == 1
    assert api.cursor_calls == 1


@pytest.mark.parametrize("awareness", [0, 1, 3, -1])
def test_already_set_incompatible_dpi_awareness_is_not_accepted(awareness):
    api = FakePointerApi(
        set_result=False,
        last_error=windows.ERROR_ACCESS_DENIED,
        current_awareness=awareness,
    )

    with pytest.raises(windows.Win32ApiError, match="incompatible"):
        windows.WindowsPointerBackend(api).list_displays()

    assert api.display_calls == 0


def test_dpi_awareness_failure_has_explicit_win32_error():
    api = FakePointerApi(set_result=False, last_error=87)

    with pytest.raises(windows.Win32ApiError, match=r"SetProcessDpiAwarenessContext.*87"):
        windows.WindowsPointerBackend(api).get_cursor_position()


def test_display_records_preserve_physical_negative_and_primary_geometry():
    api = FakePointerApi(
        displays=[
            _record(
                0,
                0,
                2560,
                1440,
                r"\\.\DISPLAY1",
                r"\\?\DISPLAY#PRIMARY#A",
                True,
            ),
            _record(
                -1920,
                -200,
                0,
                880,
                r"\\.\DISPLAY2",
                None,
                False,
            ),
        ]
    )

    displays = windows.WindowsPointerBackend(api).list_displays()

    assert displays[0].origin_x == 0.0
    assert displays[0].origin_y == 0.0
    assert displays[0].width_pts == 2560.0
    assert displays[0].height_pts == 1440.0
    assert displays[0].width_px == 2560
    assert displays[0].height_px == 1440
    assert displays[0].primary is True
    assert displays[0].id == r"\\?\DISPLAY#PRIMARY#A"
    assert displays[0].aliases == (r"\\.\DISPLAY1",)

    assert displays[1].origin_x == -1920.0
    assert displays[1].origin_y == -200.0
    assert displays[1].width_px == 1920
    assert displays[1].height_px == 1080
    assert displays[1].id == r"\\.\DISPLAY2"
    assert displays[1].aliases == (r"\\.\DISPLAY2",)
    assert displays[1].primary is False
    assert displays[1].metadata["coordinate_space"] == "physical_pixels"


@pytest.mark.parametrize(
    "rect",
    [
        (0, 0, 1920, 1080),
        (1920, 0, 4320, 1350),
        (-2560, -1440, 0, 0),
        (0, 1080, 3840, 3240),
    ],
)
def test_mixed_dpi_contract_uses_physical_pixel_dimensions(rect):
    left, top, right, bottom = rect
    api = FakePointerApi(
        displays=[_record(left, top, right, bottom, r"\\.\DISPLAY1", None, True)]
    )

    display = windows.WindowsPointerBackend(api).list_displays()[0]

    assert display.origin_x == left
    assert display.origin_y == top
    assert display.width_pts == display.width_px == right - left
    assert display.height_pts == display.height_px == bottom - top


def test_cursor_position_uses_same_physical_virtual_screen_space():
    api = FakePointerApi(cursor=(-1920.0, -200.0))

    assert windows.WindowsPointerBackend(api).get_cursor_position() == (
        -1920.0,
        -200.0,
    )
    assert api.set_calls == [windows.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2]


def test_invalid_monitor_rectangle_is_an_explicit_api_error():
    api = FakePointerApi(
        displays=[_record(10, 10, 10, 20, r"\\.\DISPLAY1", None, True)]
    )

    with pytest.raises(windows.Win32ApiError, match="invalid"):
        windows.WindowsPointerBackend(api).list_displays()


class _FakeFunction:
    def __init__(self, implementation):
        self.implementation = implementation
        self.calls = []
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.implementation(*args)


class _FakeUser32:
    def __init__(self):
        self.monitor_info = _FakeFunction(self._get_monitor_info)
        self.display_devices = _FakeFunction(self._enum_display_devices)
        self.monitor_enumerator = _FakeFunction(self._enum_display_monitors)
        self.set_dpi = _FakeFunction(lambda _context: 1)
        self.get_thread_context = _FakeFunction(lambda: 1)
        self.get_awareness = _FakeFunction(lambda _context: 2)
        self.cursor = _FakeFunction(self._get_cursor_pos)
        self.fail_monitor_info = False
        self.device_flags = None
        self.device_cb = None
        self.monitor_info_cb = None

    def __getattr__(self, name):
        functions = {
            "GetMonitorInfoW": self.monitor_info,
            "EnumDisplayDevicesW": self.display_devices,
            "EnumDisplayMonitors": self.monitor_enumerator,
            "SetProcessDpiAwarenessContext": self.set_dpi,
            "GetThreadDpiAwarenessContext": self.get_thread_context,
            "GetAwarenessFromDpiAwarenessContext": self.get_awareness,
            "GetCursorPos": self.cursor,
        }
        try:
            return functions[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def _enum_display_monitors(self, _hdc, _clip, callback, _data):
        return callback(1, None, None, 0)

    def _get_monitor_info(self, _monitor, info_pointer):
        self.monitor_info_cb = ctypes.cast(
            info_pointer,
            ctypes.POINTER(windows._MONITORINFOEXW),
        ).contents
        if self.fail_monitor_info:
            return 0
        self.monitor_info_cb.rcMonitor.left = -1920
        self.monitor_info_cb.rcMonitor.top = -100
        self.monitor_info_cb.rcMonitor.right = 0
        self.monitor_info_cb.rcMonitor.bottom = 980
        self.monitor_info_cb.dwFlags = windows.MONITORINFOF_PRIMARY
        self.monitor_info_cb.szDevice = r"\\.\DISPLAY2"
        return 1

    def _enum_display_devices(self, _device, _index, device_pointer, flags):
        self.device_flags = flags
        device = ctypes.cast(
            device_pointer,
            ctypes.POINTER(windows._DISPLAY_DEVICEW),
        ).contents
        self.device_cb = device.cb
        device.DeviceID = r"\\?\DISPLAY#INTERFACE#B"
        return 1

    def _get_cursor_pos(self, point_pointer):
        point = ctypes.cast(point_pointer, ctypes.POINTER(windows._POINT)).contents
        point.x = -1920
        point.y = -100
        return 1


def test_ctypes_adapter_uses_obs_display_interface_identity_and_struct_sizes():
    user32 = _FakeUser32()
    api = windows._CtypesWin32Api(user32=user32, last_error=lambda: 123)
    backend = windows.WindowsPointerBackend(api)

    displays = backend.list_displays()

    assert displays[0].id == r"\\?\DISPLAY#INTERFACE#B"
    assert displays[0].aliases == (r"\\.\DISPLAY2",)
    assert displays[0].origin_x == -1920.0
    assert displays[0].origin_y == -100.0
    assert displays[0].primary is True
    assert user32.device_flags == windows.EDD_GET_DEVICE_INTERFACE_NAME
    assert user32.device_cb == ctypes.sizeof(windows._DISPLAY_DEVICEW)
    assert user32.monitor_info_cb.cbSize == ctypes.sizeof(windows._MONITORINFOEXW)
    assert user32.set_dpi.calls
    assert ctypes.cast(
        user32.set_dpi.calls[0][0], ctypes.c_void_p
    ).value == ctypes.c_void_p(
        windows.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    ).value


def test_enum_display_devices_failure_falls_back_to_sz_device_alias():
    user32 = _FakeUser32()
    user32.display_devices = _FakeFunction(lambda *_args: 0)
    api = windows._CtypesWin32Api(user32=user32, last_error=lambda: 2)

    display = windows.WindowsPointerBackend(api).list_displays()[0]

    assert display.id == r"\\.\DISPLAY2"
    assert display.aliases == (r"\\.\DISPLAY2",)


def test_native_monitor_api_failure_does_not_return_fake_geometry():
    user32 = _FakeUser32()
    user32.fail_monitor_info = True
    api = windows._CtypesWin32Api(user32=user32, last_error=lambda: 87)

    with pytest.raises(windows.Win32ApiError, match=r"GetMonitorInfoW.*87"):
        windows.WindowsPointerBackend(api).list_displays()


def test_native_cursor_api_failure_is_explicit():
    user32 = _FakeUser32()
    user32.cursor = _FakeFunction(lambda _point: 0)
    api = windows._CtypesWin32Api(user32=user32, last_error=lambda: 5)

    with pytest.raises(windows.Win32ApiError, match=r"GetCursorPos.*5"):
        windows.WindowsPointerBackend(api).get_cursor_position()
