# Codex model-routing validation

Date: 2026-08-18

## Result

The Codex Desktop subagent router accepted and completed both required Windows 11 routes. No repository files were modified by either smoke agent.

| Route | Explicit model | Reasoning effort | Result |
| --- | --- | --- | --- |
| `windows_worker` | `gpt-5.6-luna` | `max` | PASS |
| `windows_arbitrator` | `gpt-5.6-sol` | `xhigh` | PASS |

Returned markers:

```text
ROUTE_OK windows_worker gpt-5.6-luna max
ROUTE_OK windows_arbitrator gpt-5.6-sol xhigh
```

Static configuration validation also passed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/validate_model_routing.ps1 -Json
```

The checked standalone Codex executable is `C:\Users\Wells\AppData\Local\Programs\OpenAI\Codex\bin\codex.EXE`, version `codex-cli 0.147.0`. With OpenAI network access, `codex login status` returned `Logged in using ChatGPT`; multi-agent is enabled and both configured GPT-5.6 models are present. Unattended CLI dispatch is therefore enabled.

## Network boundary

The login check must run with OpenAI network access. In this desktop thread, the ordinary sandbox has network disabled; inside that sandbox the same valid local ChatGPT token caused `codex login status` to print `Not logged in`. The network-enabled controller check passed, so the sandbox result is recorded as an indeterminate network false-negative, not an account logout.

## Fail-closed boundary

- Every worker spawn must explicitly request `gpt-5.6-luna` and `max`, or use the validated `windows_worker` custom agent.
- Every arbitration spawn must explicitly request `gpt-5.6-sol` and `xhigh`, or use the validated `windows_arbitrator` custom agent.
- If a spawn rejects either override or its route metadata cannot be verified, the ticket remains `Blocked`; the parent model must not substitute itself.
