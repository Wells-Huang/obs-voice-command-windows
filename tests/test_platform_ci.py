from pathlib import Path


WORKFLOW = Path(".github/workflows/ci.yml")


def test_layer_a_runs_locked_windows_and_macos_product_smoke():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    windows_job = workflow.split("  macos_regression:", 1)[0]

    assert "runs-on: windows-latest" in workflow
    assert "runs-on: macos-latest" in workflow
    assert workflow.count("uv sync --frozen") == 3
    assert "Verify Windows imports stay Quartz-free" in workflow
    assert "import obs_voice_command.os_zoom" in workflow
    assert "import obs_voice_command.main" in workflow
    assert "obs-voice-command --help" in workflow
    assert "python -m pytest tests -q" in workflow
    assert "        env:\n          PYTHONIOENCODING: utf-8\n        run:" in windows_job


def test_package_job_builds_and_imports_the_wheel():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    package_job = workflow.split("  package:", 1)[1].split("  required_gate:", 1)[0]

    assert "uv build" in workflow
    assert "*.whl" in workflow
    assert "*.tar.gz" in workflow
    assert 'artifact_env="$artifact_dir/venv"' in package_job
    assert 'uv venv "$artifact_env"' in package_job
    assert 'uv pip install --python "$artifact_env/bin/python" --no-deps "$wheel_path"' in package_job
    assert 'cd "$artifact_dir"' in package_job
    assert 'import obs_voice_command.os_zoom' in package_job
    assert 'import obs_voice_command.platform.windows' in package_job
    assert 'is_relative_to(site_packages)' in package_job
    assert 'import obs_voice_command.main' not in package_job
    assert "built artifact import: PASS" in workflow
