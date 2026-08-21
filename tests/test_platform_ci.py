from pathlib import Path


WORKFLOW = Path(".github/workflows/ci.yml")


def test_layer_a_runs_locked_windows_and_macos_product_smoke():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: windows-latest" in workflow
    assert "runs-on: macos-latest" in workflow
    assert workflow.count("uv sync --frozen") == 3
    assert "Verify Windows imports stay Quartz-free" in workflow
    assert "import obs_voice_command.os_zoom" in workflow
    assert "import obs_voice_command.main" in workflow
    assert "obs-voice-command --help" in workflow
    assert "python -m pytest tests -q" in workflow


def test_package_job_builds_and_imports_the_wheel():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "uv build" in workflow
    assert "*.whl" in workflow
    assert "*.tar.gz" in workflow
    assert "uv pip install --python .venv/bin/python --reinstall --no-deps" in workflow
    assert "built artifact import: PASS" in workflow
