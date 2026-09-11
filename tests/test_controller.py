from __future__ import annotations

import threading
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from obs_voice_command.config import ZoomConfig
from obs_voice_command.main import main
from obs_voice_command.platform.common import DisplayInfo
from obs_voice_command.runtime import (
    RuntimeDependencies,
    RuntimeStartupError,
    ZoomController,
)
from obs_voice_command.zoom import Transform


DISPLAY = DisplayInfo(
    origin_x=0,
    origin_y=0,
    width_pts=1920,
    height_pts=1080,
    width_px=1920,
    height_px=1080,
    id="fake-display",
)
ORIGINAL = Transform(pos_x=7, pos_y=11, scale_x=1.0, scale_y=1.0)


class FakePointer:
    def get_displays(self):
        return [DISPLAY]

    def get_cursor_position(self):
        return (960.0, 540.0)

    def locate(self, position, displays):
        del position
        display = displays[0]
        return display, 960.0, 540.0


class FakeObs:
    def __init__(self, *, fail_first_transform=False):
        self.events: list[tuple[str, object]] = []
        self.fail_first_transform = fail_first_transform

    def connect(self):
        self.events.append(("connect", None))

    def find_display_capture(self, scene, source):
        del scene, source
        return SimpleNamespace(source_width=1920, source_height=1080)

    def get_transform(self, item):
        del item
        return ORIGINAL

    def get_canvas_size(self):
        return (1920, 1080)

    def set_transform(self, item, transform):
        del item
        self.events.append(("transform", transform))
        if self.fail_first_transform:
            self.fail_first_transform = False
            raise ConnectionError("disconnected")

    def close(self):
        self.events.append(("close", None))


def _controller(obs, *, wait=None):
    return ZoomController(
        obs=obs,
        item=object(),
        orig=ORIGINAL,
        canvas=(1920, 1080),
        src=(1920, 1080),
        zoom_cfg=ZoomConfig(level=2.0, deadzone=0.15, smoothing=0.12),
        displays=[DISPLAY],
        dry_run=False,
        pointer=FakePointer(),
        clock=lambda: 0.0,
        wait=wait,
    )


def test_normal_stop_restores_baseline_and_ignores_late_transform():
    obs = FakeObs()
    controller = None

    def one_tick(_seconds):
        controller._stop_event.set()

    controller = _controller(obs, wait=one_tick)
    controller.handle("zoom_in")
    controller.start()
    controller.join(timeout=1)
    assert not controller.is_alive()

    controller.stop()
    transforms = [event[1] for event in obs.events if event[0] == "transform"]
    assert transforms[-1] == ORIGINAL

    count_after_stop = len(obs.events)
    controller._send_transform(Transform(100, 100, 2, 2))
    assert len(obs.events) == count_after_stop


def test_stop_orders_baseline_after_inflight_transform():
    class BlockingObs(FakeObs):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def set_transform(self, item, transform):
            if transform != ORIGINAL:
                self.started.set()
                self.release.wait(timeout=1)
            super().set_transform(item, transform)

    obs = BlockingObs()
    controller = _controller(obs)
    sender = threading.Thread(
        target=controller._send_transform,
        args=(Transform(100, 100, 2, 2),),
    )
    sender.start()
    assert obs.started.wait(timeout=1)

    stopper = threading.Thread(target=controller.stop)
    stopper.start()
    obs.release.set()
    sender.join(timeout=1)
    stopper.join(timeout=1)

    assert not sender.is_alive()
    assert not stopper.is_alive()
    transforms = [event[1] for event in obs.events if event[0] == "transform"]
    assert transforms == [Transform(100, 100, 2, 2), ORIGINAL]


def test_reconnect_restores_baseline_before_idle_state():
    obs = FakeObs(fail_first_transform=True)
    waits: list[float] = []
    controller = _controller(obs, wait=waits.append)

    controller._send_transform(Transform(100, 100, 2, 2))

    assert waits == [3.0]
    assert [event[0] for event in obs.events] == [
        "transform",
        "connect",
        "transform",
    ]
    assert obs.events[-1][1] == ORIGINAL
    assert controller._target_z == 1.0

    controller.stop()
    assert obs.events[-1] == ("transform", ORIGINAL)


class FakeStream:
    def __init__(self, callback, *, enter_interrupts=False):
        self.callback = callback
        self.enter_interrupts = enter_interrupts
        self.exited = False

    def __enter__(self):
        if self.enter_interrupts:
            raise KeyboardInterrupt()
        self.callback(np.zeros((2, 1), dtype=np.float32), 2, None, None)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exited = True
        return False


class FakeAsr:
    def __init__(self, *, interrupt=False):
        self.interrupt = interrupt

    def feed(self, samples):
        del samples
        if self.interrupt:
            raise KeyboardInterrupt()
        return "", False


def _runtime_args(**overrides):
    values = {
        "config": "missing-config.toml",
        "dry_run": False,
        "os": False,
        "list_devices": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_ctrl_c_uses_same_restore_cleanup_path():
    obs = FakeObs()
    stream_holder = {}
    asr = FakeAsr(interrupt=True)

    def audio_factory(config, callback):
        del config
        stream_holder["stream"] = FakeStream(callback)
        return stream_holder["stream"]

    dependencies = RuntimeDependencies(
        model_factory=lambda: Path("fake-model"),
        asr_factory=lambda model_dir: asr,
        pointer_factory=lambda: FakePointer(),
        obs_factory=lambda config: obs,
        audio_factory=audio_factory,
        clock=lambda: 0.0,
        wait=lambda seconds: None,
    )

    main(_runtime_args(), dependencies=dependencies)

    assert stream_holder["stream"].exited is True
    transforms = [event[1] for event in obs.events if event[0] == "transform"]
    assert transforms[-1] == ORIGINAL
    assert ("close", None) in obs.events


def test_partial_audio_startup_restores_baseline():
    obs = FakeObs()

    def audio_factory(config, callback):
        del config, callback
        raise RuntimeStartupError("audio startup failed")

    dependencies = RuntimeDependencies(
        model_factory=lambda: Path("fake-model"),
        asr_factory=lambda model_dir: FakeAsr(),
        pointer_factory=lambda: FakePointer(),
        obs_factory=lambda config: obs,
        audio_factory=audio_factory,
    )

    with pytest.raises(SystemExit) as raised:
        main(_runtime_args(), dependencies=dependencies)

    assert raised.value.code == 1
    transforms = [event[1] for event in obs.events if event[0] == "transform"]
    assert transforms[-1] == ORIGINAL
