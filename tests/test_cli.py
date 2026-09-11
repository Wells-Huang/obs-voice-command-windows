from __future__ import annotations

from argparse import Namespace

import pytest

from obs_voice_command import os_zoom
from obs_voice_command.main import main
from obs_voice_command.runtime import RuntimeDependencies


def _args(**overrides):
    values = {
        "config": "missing-config.toml",
        "dry_run": False,
        "os": False,
        "list_devices": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_windows_os_rejects_before_model_audio_or_obs(monkeypatch, capsys):
    monkeypatch.setattr(os_zoom.sys, "platform", "win32")
    calls: list[str] = []

    def unexpected(name):
        def factory(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"unexpected side effect: {name}")

        return factory

    dependencies = RuntimeDependencies(
        model_factory=unexpected("model"),
        asr_factory=unexpected("asr"),
        pointer_factory=unexpected("pointer"),
        obs_factory=unexpected("obs"),
        audio_factory=unexpected("audio"),
    )

    with pytest.raises(SystemExit) as raised:
        main(_args(os=True), dependencies=dependencies)

    assert raised.value.code == 2
    assert calls == []
    assert "only on macOS" in capsys.readouterr().err


def test_list_devices_does_not_construct_model_asr_or_obs(capsys):
    calls: list[str] = []

    def unexpected(name):
        def factory(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"unexpected side effect: {name}")

        return factory

    dependencies = RuntimeDependencies(
        device_lister=lambda: ["fake microphone"],
        model_factory=unexpected("model"),
        asr_factory=unexpected("asr"),
        pointer_factory=unexpected("pointer"),
        obs_factory=unexpected("obs"),
        audio_factory=unexpected("audio"),
    )

    main(_args(list_devices=True), dependencies=dependencies)

    assert calls == []
    assert "fake microphone" in capsys.readouterr().out


def test_cli_defaults_remain_compatible(monkeypatch):
    captured = {}

    def fake_main(args, *, dependencies=None):
        captured["args"] = args
        captured["dependencies"] = dependencies

    monkeypatch.setattr("obs_voice_command.main.main", fake_main)
    monkeypatch.setattr("sys.argv", ["obs-voice-command"])

    from obs_voice_command.main import cli

    cli()

    args = captured["args"]
    assert args.config == "config.toml"
    assert args.dry_run is False
    assert args.os is False
    assert args.list_devices is False
    assert captured["dependencies"] is None
