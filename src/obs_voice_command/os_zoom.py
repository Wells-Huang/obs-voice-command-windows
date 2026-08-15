"""真 macOS 螢幕縮放（輔助使用 Zoom）：合成 Opt+Cmd 快捷鍵。

需要「系統設定 → 輔助使用 → 縮放 → 使用鍵盤快速鍵來縮放」開啟，
且執行本程式的終端機要有輔助使用權限。
"""
import time

import Quartz

_KEY_EQUAL = 24
_KEY_MINUS = 27
_CMD_OPT = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate


def _key(code: int, flags: int) -> None:
    """Synthesize a key press with given key code and flags."""
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(ev, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.05)


def zoom_in(steps: int = 2) -> None:
    """Press Opt+Cmd+= `steps` times with 0.1s between presses."""
    for _ in range(steps):
        _key(_KEY_EQUAL, _CMD_OPT)
        time.sleep(0.1)


def zoom_out() -> None:
    """Press Opt+Cmd+- 8 times (walks back to 1x from any level; extra presses at 1x are harmless)."""
    for _ in range(8):
        _key(_KEY_MINUS, _CMD_OPT)
        time.sleep(0.05)
