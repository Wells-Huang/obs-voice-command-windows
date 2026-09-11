"""Win32 pointer and display adapter.

The module is safe to import on every platform. Loading ``user32.dll`` and
calling any Win32 API is deferred until the backend is actually queried.
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any, Callable

from .common import DisplayInfo, Point
from .unsupported import UnsupportedPlatformError


# DPI awareness context values are documented as negative pseudo-handles.
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
DPI_AWARENESS_PER_MONITOR_AWARE = 2
ERROR_ACCESS_DENIED = 5
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001
MONITORINFOF_PRIMARY = 0x00000001


class Win32ApiError(RuntimeError):
    """A Win32 call failed and did not produce usable coordinate data."""

    def __init__(
        self,
        function_name: str,
        error_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.function_name = function_name
        self.api_name = function_name
        self.error_code = error_code

        message = f"{function_name} failed"
        if error_code is not None:
            message += f" (Win32 error {error_code})"
        if detail:
            message += f": {detail}"
        super().__init__(message)


# A descriptive alias is useful to callers without changing the exception
# type or its diagnostics.
WindowsApiError = Win32ApiError


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_uint32),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_uint32),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


_MONITORENUMPROC_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_MONITORENUMPROC = _MONITORENUMPROC_FACTORY(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(_RECT),
    ctypes.c_ssize_t,
)


@dataclass(frozen=True)
class _MonitorRecord:
    left: int
    top: int
    right: int
    bottom: int
    device_name: str
    interface_id: str | None
    primary: bool


class _CtypesWin32Api:
    """Small, lazily loaded ctypes wrapper used by ``WindowsPointerBackend``."""

    def __init__(
        self,
        *,
        user32: Any | None = None,
        last_error: Callable[[], int] | None = None,
    ) -> None:
        # Supplying user32 is intentionally private but makes the wrapper
        # portable to mocked unit tests without loading a real DLL.
        self._user32 = user32
        self._last_error_provider = last_error
        self._functions: dict[str, Any] = {}

    def _ensure_user32(self) -> Any:
        if self._user32 is not None:
            return self._user32

        if os.name != "nt":
            raise UnsupportedPlatformError(
                "Win32 pointer/display APIs are only available on Windows "
                f"(running on {os.name!r})"
            )

        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        except AttributeError as exc:
            raise Win32ApiError(
                "LoadLibrary(user32)", detail="ctypes.WinDLL is unavailable"
            ) from exc
        except OSError as exc:
            raise Win32ApiError("LoadLibrary(user32)", detail=str(exc)) from exc
        return self._user32

    def _function(self, name: str, restype: Any, argtypes: list[Any]) -> Any:
        function = self._functions.get(name)
        if function is not None:
            return function

        user32 = self._ensure_user32()
        try:
            function = getattr(user32, name)
        except AttributeError as exc:
            raise Win32ApiError(name, detail="function is unavailable") from exc

        # ctypes function objects expose these attributes. The guarded
        # assignment also permits lightweight callable fakes in portable tests.
        try:
            function.restype = restype
            function.argtypes = argtypes
        except AttributeError:
            pass
        self._functions[name] = function
        return function

    def get_last_error(self) -> int:
        if self._last_error_provider is not None:
            return int(self._last_error_provider())

        get_last_error = getattr(ctypes, "get_last_error", None)
        if get_last_error is None:
            return 0
        return int(get_last_error())

    def set_process_dpi_awareness_context(self, context: int) -> bool:
        function = self._function(
            "SetProcessDpiAwarenessContext",
            ctypes.c_int,
            [ctypes.c_void_p],
        )
        return bool(function(ctypes.c_void_p(context)))

    def get_current_dpi_awareness(self) -> int:
        get_context = self._function(
            "GetThreadDpiAwarenessContext",
            ctypes.c_void_p,
            [],
        )
        get_awareness = self._function(
            "GetAwarenessFromDpiAwarenessContext",
            ctypes.c_int,
            [ctypes.c_void_p],
        )

        context = get_context()
        if not context:
            raise Win32ApiError(
                "GetThreadDpiAwarenessContext",
                self.get_last_error(),
            )

        awareness = int(get_awareness(context))
        if awareness < 0:
            raise Win32ApiError(
                "GetAwarenessFromDpiAwarenessContext",
                self.get_last_error(),
            )
        return awareness

    def enumerate_monitors(self) -> list[_MonitorRecord]:
        get_monitor_info = self._function(
            "GetMonitorInfoW",
            ctypes.c_int,
            [ctypes.c_void_p, ctypes.POINTER(_MONITORINFOEXW)],
        )
        enum_display_monitors = self._function(
            "EnumDisplayMonitors",
            ctypes.c_int,
            [
                ctypes.c_void_p,
                ctypes.POINTER(_RECT),
                _MONITORENUMPROC,
                ctypes.c_ssize_t,
            ],
        )
        enum_display_devices = self._function(
            "EnumDisplayDevicesW",
            ctypes.c_int,
            [
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.POINTER(_DISPLAY_DEVICEW),
                ctypes.c_uint32,
            ],
        )

        records: list[_MonitorRecord] = []
        callback_errors: list[Win32ApiError] = []

        def visit_monitor(
            monitor_handle: Any,
            _device_context: Any,
            _monitor_rect: Any,
            _data: int,
        ) -> int:
            info = _MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
            try:
                if not get_monitor_info(
                    monitor_handle,
                    ctypes.byref(info),
                ):
                    raise Win32ApiError(
                        "GetMonitorInfoW",
                        self.get_last_error(),
                    )

                device_name = str(info.szDevice).rstrip("\x00")
                if not device_name:
                    raise Win32ApiError(
                        "GetMonitorInfoW",
                        detail="monitor returned an empty szDevice",
                    )

                interface_id: str | None = None
                display_device = _DISPLAY_DEVICEW()
                display_device.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
                if enum_display_devices(
                    device_name,
                    0,
                    ctypes.byref(display_device),
                    EDD_GET_DEVICE_INTERFACE_NAME,
                ):
                    interface_id = (
                        str(display_device.DeviceID).rstrip("\x00") or None
                    )

                rect = info.rcMonitor
                records.append(
                    _MonitorRecord(
                        left=int(rect.left),
                        top=int(rect.top),
                        right=int(rect.right),
                        bottom=int(rect.bottom),
                        device_name=device_name,
                        interface_id=interface_id,
                        primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    )
                )
            except Win32ApiError as exc:
                callback_errors.append(exc)
                return 0
            return 1

        callback = _MONITORENUMPROC(visit_monitor)
        if not enum_display_monitors(None, None, callback, 0):
            if callback_errors:
                raise callback_errors[0]
            raise Win32ApiError(
                "EnumDisplayMonitors",
                self.get_last_error(),
            )
        if callback_errors:
            raise callback_errors[0]
        return records

    def get_cursor_position(self) -> Point:
        """Return the cursor in physical screen coordinates."""
        get_cursor_pos = self._function(
            "GetCursorPos",
            ctypes.c_int,
            [ctypes.POINTER(_POINT)],
        )
        point = _POINT()
        if not get_cursor_pos(ctypes.byref(point)):
            raise Win32ApiError("GetCursorPos", self.get_last_error())
        return float(point.x), float(point.y)


class WindowsPointerBackend:
    """Read physical-pixel display geometry and cursor position on Windows."""

    def __init__(self, api: Any | None = None) -> None:
        # Construction is deliberately side-effect free: no DLL is loaded and
        # no process DPI setting is changed until a query is requested.
        self._api = _CtypesWin32Api() if api is None else api
        self._coordinate_space_initialized = False

    def initialize_coordinate_space(self) -> None:
        """Require a compatible Per-Monitor DPI coordinate space."""
        if self._coordinate_space_initialized:
            return

        if self._api.set_process_dpi_awareness_context(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ):
            self._coordinate_space_initialized = True
            return

        error_code = int(self._api.get_last_error())
        if error_code != ERROR_ACCESS_DENIED:
            raise Win32ApiError(
                "SetProcessDpiAwarenessContext",
                error_code,
            )

        # Windows reports ERROR_ACCESS_DENIED when another component or the
        # application manifest already selected process DPI awareness. Do not
        # assume that it is compatible: query the current context explicitly.
        current_awareness = int(self._api.get_current_dpi_awareness())
        if current_awareness != DPI_AWARENESS_PER_MONITOR_AWARE:
            raise Win32ApiError(
                "SetProcessDpiAwarenessContext",
                error_code,
                "process already uses incompatible DPI awareness "
                f"{current_awareness}; expected per-monitor awareness",
            )

        self._coordinate_space_initialized = True

    def _ensure_coordinate_space(self) -> None:
        self.initialize_coordinate_space()

    def list_displays(self) -> list[DisplayInfo]:
        """Return physical-pixel rectangles in virtual-screen coordinates."""
        self._ensure_coordinate_space()

        displays: list[DisplayInfo] = []
        for record in self._api.enumerate_monitors():
            left = int(record.left)
            top = int(record.top)
            right = int(record.right)
            bottom = int(record.bottom)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                raise Win32ApiError(
                    "GetMonitorInfoW",
                    detail=(
                        "monitor rectangle is invalid: "
                        f"({left}, {top}, {right}, {bottom})"
                    ),
                )

            device_name = str(record.device_name)
            interface_id = record.interface_id or None
            display_id = interface_id or device_name
            aliases = (device_name,) if device_name else ()
            displays.append(
                DisplayInfo(
                    origin_x=float(left),
                    origin_y=float(top),
                    width_pts=float(width),
                    height_pts=float(height),
                    width_px=width,
                    height_px=height,
                    id=display_id,
                    aliases=aliases,
                    primary=bool(record.primary),
                    metadata={
                        "coordinate_space": "physical_pixels",
                        "device_name": device_name,
                        "device_interface_id": interface_id,
                    },
                )
            )
        return displays

    def get_cursor_position(self) -> Point:
        """Return the cursor in the same physical-pixel space as displays."""
        self._ensure_coordinate_space()
        return self._api.get_cursor_position()


__all__ = [
    "DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2",
    "DPI_AWARENESS_PER_MONITOR_AWARE",
    "EDD_GET_DEVICE_INTERFACE_NAME",
    "ERROR_ACCESS_DENIED",
    "MONITORINFOF_PRIMARY",
    "Win32ApiError",
    "WindowsApiError",
    "WindowsPointerBackend",
]
