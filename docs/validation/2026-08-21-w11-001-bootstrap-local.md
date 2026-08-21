# W11-001 bootstrap workflow local evidence

Date: 2026-08-21 (Asia/Taipei)  
Ticket: W11-001  
Branch: `codex/w11-001-bootstrap`

## Scope

This evidence covers the dependency-lazy bootstrap workflow only. It does not
install the project, download an ASR model, open a microphone, start OBS, or
perform live Layer B validation.

The workflow emits `ci_stage=bootstrap` in each required job summary and in a
separate artifact directory. Its only external actions are pinned
`actions/checkout`, `actions/setup-python`, and `actions/upload-artifact`, with
workflow permission limited to `contents: read`.

Stable job names:

- `layer-a / windows-unit`
- `layer-a / macos-regression`
- `layer-a / package`
- `required / gate`

The aggregate gate uses `if: ${{ always() }}` and fails unless all three
required job results are exactly `success`. No required job uses
`continue-on-error`.

## Checks

The following local commands are run without project installation or shared
runtime mutation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/validate_model_routing.ps1
python -m unittest -v tests.test_inspect_obs_contract tests.test_model_routing
python -m compileall -q tools tests
```

The local read-only OBS probe may return `MISSING_OBS` or
`UNREACHABLE_ENDPOINT`; either result is acceptable for W11-001 and does not
activate Layer B.

## Results

| Command/check | Result |
| --- | --- |
| `powershell -NoProfile -ExecutionPolicy Bypass -File tools/validate_model_routing.ps1` | PASS; implementer route is `windows_worker -> gpt-5.6-luna (max)` and arbitrator route is `windows_arbitrator -> gpt-5.6-sol (xhigh)`. |
| `python -m unittest -v tests.test_inspect_obs_contract tests.test_model_routing` | PASS; 9 tests. The default sandbox denied one temporary-directory write; the unchanged suite passed when rerun with normal local filesystem access. |
| `python -m compileall -q tools tests` | PASS. |
| `python tools/inspect_obs_contract.py --host 127.0.0.1 --port 4455 --timeout 0.5 --json` | Exit 3, `UNREACHABLE_ENDPOINT`; accepted and sanitized, with `password_value_exposed=false`. |
| Planning-artifact check used by the workflow | PASS. |
| Ruby Psych parse of `.github/workflows/ci.yml` | PASS. |
| `git diff --check` | PASS. |
