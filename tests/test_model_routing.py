from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tools import validate_model_routing as routing


ROOT = Path(__file__).resolve().parents[1]


class ModelRoutingTests(unittest.TestCase):
    def test_repository_model_routing_is_consistent(self) -> None:
        report = routing.validate_repository(ROOT)

        self.assertEqual(report.errors, [])
        self.assertEqual(report.routes["implementer"]["model"], "gpt-5.6-luna")
        self.assertEqual(
            report.routes["implementer"]["model_reasoning_effort"], "max"
        )
        self.assertEqual(report.routes["arbitrator"]["model"], "gpt-5.6-sol")
        self.assertEqual(
            report.routes["arbitrator"]["model_reasoning_effort"], "xhigh"
        )

    def test_manifest_model_profiles_parser_stops_at_next_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.yml"
            manifest.write_text(
                """model_profiles:
  implementer:
    codex_agent: windows_worker
    model: gpt-5.6-luna
    model_reasoning_effort: max
execution_defaults:
  worker_profile: implementer
""",
                encoding="utf-8",
            )

            profiles = routing.read_model_profiles(manifest)

        self.assertEqual(
            profiles,
            {
                "implementer": {
                    "codex_agent": "windows_worker",
                    "model": "gpt-5.6-luna",
                    "model_reasoning_effort": "max",
                }
            },
        )

    def test_w11_001_manifest_has_verified_external_gate_and_no_dependencies(self) -> None:
        manifest = (
            ROOT / "docs" / "plans" / "2026-08-17-windows-11-ticket-manifest.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("baseline_commit: de6c588f981596ed13bc9cd0254ad4989a2686b3", manifest)
        self.assertIn("target_branch: develop", manifest)
        self.assertIn("required_check: required / gate", manifest)
        self.assertRegex(
            manifest,
            r"(?ms)^external_predecessor_gates:\n.*?^\s{4}state: policy_verified$",
        )

        ticket_match = re.search(
            r"(?ms)^  - id: W11-001\n(?P<body>.*?)(?=^  - id: W11-002\n)",
            manifest,
        )
        self.assertIsNotNone(ticket_match)
        ticket_body = ticket_match.group("body") if ticket_match else ""
        self.assertRegex(ticket_body, r"(?m)^    depends_on: \[\]$")
        self.assertRegex(
            ticket_body,
            r"(?m)^    depends_on_external: \[empty_origin_baseline_seed\]$",
        )
        self.assertRegex(ticket_body, r"(?m)^    ci_stage: bootstrap$")

    def test_w11_002_workflow_is_full_activation_with_stable_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        for job_name in (
            "name: layer-a / windows-unit",
            "name: layer-a / macos-regression",
            "name: layer-a / package",
            "name: required / gate",
        ):
            self.assertIn(job_name, workflow)

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("CI_STAGE: full_activation", workflow)
        self.assertIn("uv sync --frozen", workflow)
        self.assertIn("if: ${{ always() }}", workflow)
        self.assertIn("needs: [windows_unit, macos_regression, package]", workflow)
        self.assertIn("needs.windows_unit.result", workflow)
        self.assertIn("needs.macos_regression.result", workflow)
        self.assertIn("needs.package.result", workflow)
        self.assertNotIn("continue-on-error", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("CI_STAGE: bootstrap", workflow)
        self.assertNotIn("ci_stage=bootstrap", workflow)

        workflow_lower = workflow.lower()
        for forbidden in (
            "ensure_model",
            "sounddevice.query",
            "127.0.0.1:4455",
            "setsceneitemtransform",
            "self-hosted",
            "sounddevice.inputstream",
            "obs64.exe",
            "obs32.exe",
            "start-process obs",
            "open -a obs",
        ):
            self.assertNotIn(forbidden, workflow_lower)

        action_uses = re.findall(
            r"(?m)^\s+uses:\s+([^\s#]+)(?:\s+#.*)?$", workflow
        )
        self.assertGreaterEqual(len(action_uses), 3)
        for action_use in action_uses:
            self.assertRegex(action_use, r"^[^@]+@[0-9a-f]{40}$")

        gate_match = re.search(
            r"(?ms)^  required_gate:\n(?P<body>.*)\Z", workflow
        )
        self.assertIsNotNone(gate_match)
        gate_body = gate_match.group("body") if gate_match else ""
        self.assertRegex(
            gate_body,
            r'(?s)if \[\[ "\$CI_STAGE" != "full_activation" \]\]; then.*?exit 1.*?fi',
        )


if __name__ == "__main__":
    unittest.main()
