import subprocess
import sys

import pytest


def _run_isolated(code: str):
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def test_os_zoom_import_is_quartz_lazy():
    result = _run_isolated(
        "import sys; import obs_voice_command.os_zoom; "
        "assert 'Quartz' not in sys.modules"
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows import contract")
def test_windows_main_import_does_not_load_quartz():
    result = _run_isolated(
        "import sys; import obs_voice_command.main; "
        "assert 'Quartz' not in sys.modules"
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CLI contract")
def test_windows_cli_help_does_not_load_quartz():
    result = _run_isolated(
        "import sys; from obs_voice_command import main; "
        "assert 'Quartz' not in sys.modules; "
        "sys.argv=['obs-voice-command','--help']; "
        "exec(\"try:\\n main.cli()\\nexcept SystemExit as exc:\\n assert exc.code == 0\"); "
        "assert 'Quartz' not in sys.modules"
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
