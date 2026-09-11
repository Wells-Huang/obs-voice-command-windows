"""主程式：CLI composition root for the voice-command zoom runtime."""
from __future__ import annotations

import argparse
import sys

from . import os_zoom
from .platform import UnsupportedPlatformError
from .runtime import (
    Runtime,
    RuntimeDependencies,
    RuntimeStartupError,
    ZoomController,
)


def main(args, *, dependencies: RuntimeDependencies | None = None) -> None:
    """Run the application with optional hardware-free dependencies."""
    try:
        Runtime(args, dependencies).run()
    except UnsupportedPlatformError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except RuntimeStartupError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def cli(dependencies: RuntimeDependencies | None = None) -> None:
    """Parse command-line flags and run the composed application."""
    parser = argparse.ArgumentParser(
        description="Voice-commanded zoom-to-mouse for OBS"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.toml",
        help="Path to config file (default: config.toml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print transforms instead of sending to OBS",
    )
    parser.add_argument(
        "--os",
        action="store_true",
        help="用真 macOS 螢幕縮放（輔助使用 Zoom）取代 OBS transform 縮放；"
        "同一組語音詞，需開啟「使用鍵盤快速鍵來縮放」與終端機輔助使用權限",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List audio devices and exit",
    )

    args = parser.parse_args()
    main(args, dependencies=dependencies)


__all__ = [
    "Runtime",
    "RuntimeDependencies",
    "ZoomController",
    "cli",
    "main",
    "os_zoom",
]
