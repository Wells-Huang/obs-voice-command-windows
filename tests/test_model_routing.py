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

    def test_w11_001_workflow_is_bootstrap_only_and_has_stable_gate(self) -> None:
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
        self.assertGreaterEqual(workflow.count("ci_stage=bootstrap"), 4)
        self.assertIn("if: ${{ always() }}", workflow)
        self.assertIn("needs: [windows_unit, macos_regression, package]", workflow)
        self.assertIn("needs.windows_unit.result", workflow)
        self.assertIn("needs.macos_regression.result", workflow)
        self.assertIn("needs.package.result", workflow)
        self.assertNotIn("continue-on-error", workflow)
        self.assertNotIn("secrets.", workflow)

        for forbidden in (
            "uv sync",
            "pip install",
            "sherpa-onnx",
            "sounddevice",
            "SetSceneItemTransform",
        ):
            self.assertNotIn(forbidden, workflow)

        action_refs = re.findall(
            r"uses:\s+[^\s@]+@([0-9a-f]{40})(?:\s|$)", workflow, flags=re.MULTILINE
        )
        self.assertGreaterEqual(len(action_refs), 3)


if __name__ == "__main__":
    unittest.main()
