from pathlib import Path


WORKFLOW = Path(".github/workflows/ci.yml")


def test_layer_a_runs_locked_windows_and_macos_product_smoke():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    matrix_job = workflow.split("  platform_matrix:", 1)[1].split("  package:", 1)[0]

    assert "name: ${{ matrix.check_name }}" in matrix_job
    assert "runs-on: ${{ matrix.os }}" in matrix_job
    assert "strategy:\n      fail-fast: false\n      matrix:\n        include:" in matrix_job
    assert matrix_job.count("check_name:") == 2
    assert "os: windows-latest" in matrix_job
    assert "python: '3.12'" in matrix_job
    assert "check_name: layer-a / windows-unit" in matrix_job
    assert "os: macos-latest" in matrix_job
    assert "check_name: layer-a / macos-regression" in matrix_job
    assert "python-version: ${{ matrix.python }}" in matrix_job
    assert "shell: ${{" not in workflow
    assert "  windows_unit:" not in workflow
    assert "  macos_regression:" not in workflow
    assert matrix_job.count("uv sync --frozen") == 1
    assert workflow.count("uv sync --frozen") == 2
    assert "Verify Windows imports stay Quartz-free" in workflow
    assert "Verify macOS imports and CLI" in workflow
    assert "import obs_voice_command.os_zoom" in workflow
    assert "import obs_voice_command.main" in workflow
    assert "obs-voice-command --help" in workflow
    assert matrix_job.count("python -m pytest tests -q") == 2
    assert "Platform guard (Windows)" in matrix_job
    assert "if: ${{ matrix.platform == 'windows' }}" in matrix_job
    assert "shell: pwsh" in matrix_job
    assert "Platform guard (macOS)" in matrix_job
    assert "if: ${{ matrix.platform == 'macos' }}" in matrix_job
    assert "shell: bash" in matrix_job


def test_windows_utf8_output_is_job_scoped_before_smoke_and_tests():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    matrix_job = workflow.split("  platform_matrix:", 1)[1].split("  package:", 1)[0]
    windows_entry = matrix_job.split("          - os: windows-latest", 1)[1].split(
        "          - os: macos-latest", 1
    )[0]
    macos_entry = matrix_job.split("          - os: macos-latest", 1)[1].split(
        "    env:", 1
    )[0]

    job_env = "    env:\n      PYTHONIOENCODING: ${{ matrix.python_io_encoding }}\n    steps:"
    encoding_index = matrix_job.index(job_env)
    smoke_index = matrix_job.index("      - name: Verify Windows imports stay Quartz-free")
    tests_index = matrix_job.index("      - name: Run Windows hardware-free tests")

    assert encoding_index < smoke_index
    assert encoding_index < tests_index
    assert "python_io_encoding: utf-8" in windows_entry
    assert "python_io_encoding: utf-8" not in macos_entry
    assert matrix_job.count("\n      PYTHONIOENCODING:") == 1
    assert "PYTHONIOENCODING: utf-8" not in workflow.split("jobs:", 1)[0]


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


def test_required_gate_aggregates_matrix_and_package_fail_closed():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    gate = workflow.split("  required_gate:", 1)[1]

    assert "name: required / gate" in gate
    assert "if: ${{ always() }}" in gate
    assert "needs: [platform_matrix, package]" in gate
    assert "PLATFORM_MATRIX_RESULT: ${{ needs.platform_matrix.result }}" in gate
    assert "PACKAGE_RESULT: ${{ needs.package.result }}" in gate
    assert '"$PLATFORM_MATRIX_RESULT" != "success"' in gate
    assert '"$PACKAGE_RESULT" != "success"' in gate
    assert "CI_STAGE: full" in workflow
    assert '"$CI_STAGE" != "full"' in gate
    assert "full_activation" not in workflow
    assert "bootstrap" not in workflow.lower()
