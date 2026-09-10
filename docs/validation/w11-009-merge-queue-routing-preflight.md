# W11-009 routing preflight

- Verified at: `2026-09-10T20:10:10.439+08:00` (Asia/Taipei)
- Execution context: `codex_exec_desktop`
- Current arbitration route: `windows_arbitrator` → `gpt-6-astra` / `medium`
- Current implementation route: `windows_worker` → `gpt-5.6-luna` / `max`
- Route sources: `.codex/agents/windows-arbitrator.toml`,
  `.codex/agents/windows-worker.toml`, and the manifest `model_profiles`.
- Controller report: current Astra route was accepted by the desktop spawn with
  the explicit model and reasoning-effort metadata; no generic or parent-model
  fallback was used.

## Checks

Exact bundled runtime used (the repository `.venv` trampoline is not used):

```powershell
& 'C:\Users\Wells\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools\validate_model_routing.py --root (Get-Location)
```

Result: `model routing: PASS`; implementer and arbitrator routes matched the
manifest and custom-agent pins.

```powershell
& 'C:\Users\Wells\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_model_routing -v
```

Result: `Ran 4 tests ... OK`. The first sandboxed attempt was not evidence of a
code failure: the standard-library `TemporaryDirectory` write was denied by the
sandbox. The same exact command passed outside the sandbox using the bundled
runtime.

The older `docs/validation/2026-08-18-model-routing-smoke.md` remains preserved
as historical standalone/Sol-route evidence. It is not the current routing
override or preflight source.
