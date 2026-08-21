"""Validate the executable Codex model-routing contract for Windows tickets."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path("docs/plans/2026-08-17-windows-11-ticket-manifest.yml")
REQUIRED_PROFILES = ("implementer", "arbitrator")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    routes: dict[str, dict[str, str]] = field(default_factory=dict)
    cli: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "routes": self.routes,
            "cli": self.cli,
        }


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        lowered = value.lower()
        if lowered == "null":
            return None
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return value


def read_model_profiles(path: Path) -> dict[str, dict[str, Any]]:
    """Read only the shallow model_profiles mapping from the YAML manifest.

    The manifest owns a much larger YAML document. This parser deliberately accepts
    only the two-level scalar section used by the router, keeping this validation
    tool dependency-free on a fresh Windows checkout.
    """

    profiles: dict[str, dict[str, Any]] = {}
    current: str | None = None
    in_section = False

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            if stripped == "model_profiles:":
                in_section = True
                current = None
                continue
            if in_section:
                break
            continue

        if not in_section:
            continue
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1]
            profiles[current] = {}
            continue
        if indent == 4 and current and ":" in stripped:
            key, value = stripped.split(":", 1)
            profiles[current][key.strip()] = _parse_scalar(value)
            continue
        raise ValueError(
            f"unsupported model_profiles syntax at {path}:{line_number}: {raw_line}"
        )

    return profiles


def read_agent_files(agent_dir: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    agents: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(agent_dir.glob("*.toml")):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        name = data.get("name")
        if isinstance(name, str) and name:
            if name in agents:
                raise ValueError(f"duplicate custom agent name {name!r}")
            agents[name] = (path, data)
    return agents


def validate_repository(root: Path, *, check_cli: bool = False, codex_bin: str = "codex") -> ValidationReport:
    root = root.resolve()
    report = ValidationReport()
    manifest_path = root / DEFAULT_MANIFEST
    config_path = root / ".codex" / "config.toml"
    agent_dir = root / ".codex" / "agents"

    try:
        profiles = read_model_profiles(manifest_path)
    except (OSError, ValueError) as exc:
        report.errors.append(f"cannot read manifest routing profiles: {exc}")
        return report

    try:
        with config_path.open("rb") as handle:
            project_config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        report.errors.append(f"cannot read project Codex config: {exc}")
        return report

    try:
        agents = read_agent_files(agent_dir)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        report.errors.append(f"cannot read custom agents: {exc}")
        return report

    # Codex CLI 0.144.1 treats project-level ``[agents.<name>]`` entries as
    # role definitions. Global subagent defaults are therefore owned by the
    # manifest's execution_defaults, while .codex/agents/*.toml owns the
    # executable route pins. Keep accepting an empty project config so the
    # standalone CLI can load the project without interpreting global-default
    # keys as malformed agent roles.
    project_agents = project_config.get("agents")
    if project_agents is not None and not isinstance(project_agents, dict):
        report.errors.append(".codex/config.toml agents must be a TOML table when present")

    for profile_name in REQUIRED_PROFILES:
        profile = profiles.get(profile_name)
        if profile is None:
            report.errors.append(f"manifest is missing model profile {profile_name!r}")
            continue

        required = ("codex_agent", "model", "model_reasoning_effort", "sandbox_mode")
        missing = [key for key in required if not profile.get(key)]
        if missing:
            report.errors.append(
                f"manifest profile {profile_name!r} is missing: {', '.join(missing)}"
            )
            continue

        agent_name = str(profile["codex_agent"])
        entry = agents.get(agent_name)
        if entry is None:
            report.errors.append(
                f"manifest profile {profile_name!r} references unknown custom agent {agent_name!r}"
            )
            continue

        agent_path, agent = entry
        missing_agent_fields = [
            key
            for key in ("name", "description", "developer_instructions")
            if not agent.get(key)
        ]
        if missing_agent_fields:
            report.errors.append(
                f"{agent_path.relative_to(root)} is missing: {', '.join(missing_agent_fields)}"
            )
        route = {
            "agent": agent_name,
            "model": str(profile["model"]),
            "model_reasoning_effort": str(profile["model_reasoning_effort"]),
            "sandbox_mode": str(profile["sandbox_mode"]),
            "agent_file": str(agent_path.relative_to(root)),
        }
        report.routes[profile_name] = route

        for key in ("model", "model_reasoning_effort", "sandbox_mode"):
            if agent.get(key) != profile.get(key):
                report.errors.append(
                    f"{agent_path.relative_to(root)} {key}={agent.get(key)!r} does not match "
                    f"manifest {profile_name}.{key}={profile.get(key)!r}"
                )

    if check_cli:
        _check_codex_cli(report, codex_bin)

    return report


def _run_codex(codex_bin: str, *args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(codex_bin) if Path(codex_bin).name == codex_bin else codex_bin
    if not executable:
        raise FileNotFoundError(f"Codex executable not found: {codex_bin}")
    return subprocess.run(
        [executable, *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _check_codex_cli(report: ValidationReport, codex_bin: str) -> None:
    try:
        executable = (
            shutil.which(codex_bin) if Path(codex_bin).name == codex_bin else codex_bin
        )
        if not executable:
            raise FileNotFoundError(f"Codex executable not found: {codex_bin}")
        report.cli["executable"] = str(executable)
        version = _run_codex(codex_bin, "--version")
        login = _run_codex(codex_bin, "login", "status")
        features = _run_codex(codex_bin, "features", "list")
        catalog = _run_codex(codex_bin, "debug", "models")
    except OSError as exc:
        report.errors.append(f"Codex CLI preflight failed: {exc}")
        return

    report.cli["version"] = version.stdout.strip() or version.stderr.strip()
    if version.returncode != 0:
        report.errors.append("Codex CLI version check failed")

    authenticated = login.returncode == 0
    report.cli["authenticated"] = authenticated
    if not authenticated:
        report.errors.append(
            "Codex CLI is not authenticated; run codex login or provide approved automation credentials"
        )

    multi_agent_enabled = any(
        line.split()[:1] == ["multi_agent"] and line.split()[-1:] == ["true"]
        for line in features.stdout.splitlines()
    )
    report.cli["multi_agent_enabled"] = multi_agent_enabled
    if features.returncode != 0 or not multi_agent_enabled:
        report.errors.append("Codex CLI multi_agent feature is not enabled")

    try:
        catalog_data = json.loads(catalog.stdout)
        available_models = {
            item.get("slug") for item in catalog_data.get("models", []) if item.get("slug")
        }
    except (json.JSONDecodeError, AttributeError):
        available_models = set()
        report.errors.append("Codex CLI returned an unreadable model catalog")

    report.cli["available_models"] = sorted(available_models)
    required_models = {route["model"] for route in report.routes.values()}
    missing_models = sorted(required_models - available_models)
    if catalog.returncode != 0 or missing_models:
        report.errors.append(
            "Codex CLI model catalog is missing required routes: " + ", ".join(missing_models)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to the parent of tools/).",
    )
    parser.add_argument(
        "--check-cli",
        action="store_true",
        help="Also require the PATH Codex CLI to expose multi-agent and both configured models.",
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex executable name or path used with --check-cli.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_repository(
        args.root,
        check_cli=args.check_cli,
        codex_bin=args.codex_bin,
    )
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print("model routing: PASS" if report.ok else "model routing: FAIL")
        for name, route in report.routes.items():
            print(
                f"  {name}: {route['agent']} -> {route['model']} "
                f"({route['model_reasoning_effort']}, {route['sandbox_mode']})"
            )
        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        for error in report.errors:
            print(f"error: {error}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
