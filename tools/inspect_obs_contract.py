"""Read-only Windows OBS WebSocket and transform-contract probe.

The probe deliberately performs no OBS mutations.  It checks the local TCP
endpoint first, then uses the repository's ``obsws-python`` dependency (when
available) to read ``GetVersion``, ``GetSceneItemList``, ``GetInputSettings``,
and ``GetSceneItemTransform``.  Output is a sanitized contract summary; the
password is accepted only through an environment variable or a TOML config
file and is never printed or written to evidence.

The command is intentionally dependency-lazy so that ``--help`` and the
missing-OBS diagnostic work before a project environment has been installed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SUCCESS = "SUCCESS"
MISSING_OBS = "MISSING_OBS"
UNREACHABLE_ENDPOINT = "UNREACHABLE_ENDPOINT"
PROTOCOL_API_MISMATCH = "PROTOCOL_API_MISMATCH"
TRANSFORM_CONTRACT_FAILED = "TRANSFORM_CONTRACT_FAILED"
PROBE_DEPENDENCY_MISSING = "PROBE_DEPENDENCY_MISSING"
INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
EVIDENCE_WRITE_FAILED = "EVIDENCE_WRITE_FAILED"

EXIT_CODES = {
    SUCCESS: 0,
    MISSING_OBS: 2,
    UNREACHABLE_ENDPOINT: 3,
    PROTOCOL_API_MISMATCH: 4,
    TRANSFORM_CONTRACT_FAILED: 5,
    PROBE_DEPENDENCY_MISSING: 6,
    INVALID_CONFIGURATION: 64,
    EVIDENCE_WRITE_FAILED: 74,
}

CAPTURE_INPUT_KINDS = frozenset(
    {"monitor_capture", "display_capture", "screen_capture"}
)
MONITOR_CAPTURE_KIND = "monitor_capture"
SENSITIVE_KEY_RE = re.compile(
    r"(?:pass(?:word|wd)?|secret|token|authorization|credential|api[_-]?key|"
    r"private[_-]?key|cookie)",
    re.IGNORECASE,
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?P<key>pass(?:word|wd)?|secret|token|authorization|credential|"
    r"api[_-]?key)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)
BEARER_RE = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MISSING = object()


@dataclass(frozen=True)
class EndpointCheck:
    """Result of the side-effect-free TCP reachability check."""

    reachable: bool
    error_type: str | None = None


@dataclass(frozen=True)
class ObsInstallation:
    """Minimal local OBS detection state; no executable paths are exposed."""

    installed: bool | None
    running: bool | None
    detection_method: str


@dataclass
class ProbeResult:
    """Sanitized probe result suitable for terminal output or JSON evidence."""

    status: str
    summary: str
    endpoint: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.status, 1)

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "endpoint": self.endpoint,
            "metadata": self.metadata,
            "details": self.details,
            "evidence": self.evidence,
        }


class ProbeConfigurationError(ValueError):
    """Raised when safe probe options cannot be resolved."""


def _safe_text(
    value: Any, *, limit: int = 320, secrets: tuple[str, ...] = ()
) -> str:
    """Return bounded text with credential-like fragments removed."""

    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    text = SENSITIVE_TEXT_RE.sub(
        lambda match: f"{match.group('key')}=<redacted>", text
    )
    text = BEARER_RE.sub("Bearer <redacted>", text)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _safe_error(
    exc: BaseException, *, secrets: tuple[str, ...] = ()
) -> dict[str, str]:
    """Expose only diagnostic type and sanitized, bounded exception text."""

    return {
        "type": type(exc).__name__,
        "message": _safe_text(exc, secrets=secrets),
    }


def _name_digest(value: Any) -> str:
    """Create a short correlation digest without persisting a scene/source name."""

    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _lookup(mapping_or_object: Any, *names: str, default: Any = MISSING) -> Any:
    """Look up camelCase/snake_case response fields on mappings or objects."""

    if mapping_or_object is None:
        return default

    mapping: Mapping[Any, Any] | None = None
    if isinstance(mapping_or_object, Mapping):
        mapping = mapping_or_object
    elif hasattr(mapping_or_object, "_asdict"):
        try:
            mapping = mapping_or_object._asdict()
        except Exception:
            mapping = None
    elif hasattr(mapping_or_object, "__dict__"):
        try:
            mapping = vars(mapping_or_object)
        except TypeError:
            mapping = None

    if mapping is not None:
        normalised = {_normalise_key(key): value for key, value in mapping.items()}
        for name in names:
            key = _normalise_key(name)
            if key in normalised:
                return normalised[key]

    for name in names:
        try:
            return getattr(mapping_or_object, name)
        except AttributeError:
            continue
    return default


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "_asdict"):
        try:
            return dict(value._asdict())
        except Exception:
            return None
    if hasattr(value, "__dict__"):
        try:
            return dict(vars(value))
        except TypeError:
            return None
    return None


def _normalise_kind(value: Any) -> str:
    if value is None or value is MISSING:
        return ""
    return str(value).strip().lower().replace("-", "_")


def _is_sensitive_key(key: Any) -> bool:
    return bool(SENSITIVE_KEY_RE.search(str(key)))


def _sanitise_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively remove credentials and de-identify monitor/source strings."""

    if value is MISSING:
        return None
    if key is not None and _is_sensitive_key(key):
        return "<redacted>"

    normalised_key = _normalise_key(key or "")
    if normalised_key in {"monitorid", "monitoridentifier"}:
        if value is None or value == "":
            return {"present": False, "redacted": True}
        return {
            "present": True,
            "redacted": True,
            "sha256_12": _name_digest(value),
        }

    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitise_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitise_value(item) for item in value]
    if isinstance(value, (str, bytes)):
        if isinstance(value, bytes):
            return f"<bytes length={len(value)}>"
        # Source and scene names are not needed to validate the contract.  A
        # digest preserves correlation without exposing a user's labels.
        if normalised_key in {
            "sourcename",
            "scenename",
            "inputname",
            "filename",
            "path",
        }:
            return {"redacted": True, "sha256_12": _name_digest(value)}
        return _safe_text(value, limit=256)
    if isinstance(value, float) and not math.isfinite(value):
        return f"<{value!r}>"
    return value


def _sanitise_error_details(
    phase: str, exc: BaseException, *, secrets: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {"phase": phase, "error": _safe_error(exc, secrets=secrets)}


def _result(
    status: str,
    summary: str,
    host: str,
    port: int,
    *,
    details: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ProbeResult:
    return ProbeResult(
        status=status,
        summary=summary,
        endpoint={"host": host, "port": port},
        details=dict(details or {}),
        evidence=dict(evidence or {}),
        metadata=dict(metadata or {}),
    )


def check_tcp_endpoint(host: str, port: int, timeout: float) -> EndpointCheck:
    """Check TCP reachability without sending credentials or OBS requests."""

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return EndpointCheck(reachable=True)
    except (OSError, TimeoutError) as exc:
        return EndpointCheck(reachable=False, error_type=type(exc).__name__)


def _tasklist_has_obs() -> bool | None:
    """Return whether an OBS process is visible, without returning PIDs/output."""

    if os.name != "nt":
        return None

    found = False
    try:
        for executable in ("obs64.exe", "obs.exe"):
            completed = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"IMAGENAME eq {executable}",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=2,
            )
            if completed.returncode != 0:
                return None
            for row in csv.reader(completed.stdout.splitlines()):
                if row and row[0].strip().lower() == executable:
                    found = True
                    break
        return found
    except (OSError, subprocess.SubprocessError):
        return None


def _obs_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if not base:
            continue
        root = Path(base)
        candidates.extend(
            (
                root / "obs-studio" / "bin" / "64bit" / "obs64.exe",
                root / "obs-studio" / "bin" / "32bit" / "obs32.exe",
                root / "Programs" / "obs-studio" / "bin" / "64bit" / "obs64.exe",
            )
        )
    for name in ("obs64.exe", "obs.exe"):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    return candidates


def detect_obs_installation() -> ObsInstallation:
    """Detect OBS locally for a useful missing-vs-unreachable classification."""

    if os.name != "nt":
        return ObsInstallation(None, None, "non_windows")

    running = _tasklist_has_obs()
    executable_found = any(path.is_file() for path in _obs_executable_candidates())
    if running is True or executable_found:
        installed: bool | None = True
    elif running is False:
        installed = False
    else:
        installed = None
    method = "tasklist_and_common_install_paths"
    return ObsInstallation(installed=installed, running=running, detection_method=method)


def _load_req_client() -> type[Any]:
    try:
        from obsws_python import ReqClient
    except ImportError as exc:
        raise ModuleNotFoundError(
            "obsws-python is unavailable; run the locked project environment before "
            "performing the live OBS contract probe"
        ) from exc
    return ReqClient


def _version_evidence(version_response: Any) -> tuple[dict[str, Any], str | None]:
    obs_version = _lookup(version_response, "obsVersion", "obs_version")
    websocket_version = _lookup(
        version_response,
        "obsWebSocketVersion",
        "obs_web_socket_version",
        "obsWebsocketVersion",
    )
    if websocket_version is MISSING or websocket_version in (None, ""):
        raise ProbeConfigurationError("GetVersion did not return obsWebSocketVersion")

    version_text = str(websocket_version)
    match = re.match(r"\s*(\d+)", version_text)
    if not match or int(match.group(1)) != 5:
        raise ProbeConfigurationError(
            f"unsupported obs-websocket protocol version {version_text!r}"
        )

    return (
        {
            "obs_version": _sanitise_value(obs_version),
            "obs_websocket_version": _sanitise_value(websocket_version),
            "rpc_version": _sanitise_value(
                _lookup(version_response, "rpcVersion", "rpc_version")
            ),
        },
        version_text,
    )


def _extract_scene_items(scene_response: Any) -> list[dict[str, Any]]:
    raw_items = _lookup(scene_response, "sceneItems", "scene_items")
    if raw_items is MISSING or not isinstance(raw_items, (list, tuple)):
        raise ProbeConfigurationError(
            "GetSceneItemList did not return a sceneItems list"
        )
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        item = _as_mapping(raw_item)
        if item is None:
            raise ProbeConfigurationError(
                "GetSceneItemList contained an item with an unsupported response shape"
            )
        items.append(item)
    return items


def _scene_item_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        source_name = _lookup(item, "sourceName", "source_name", default="")
        output.append(
            {
                "source_label": f"<source-{index}>",
                "source_name_sha256_12": _name_digest(source_name),
                "scene_item_id": _sanitise_value(
                    _lookup(item, "sceneItemId", "scene_item_id")
                ),
                "input_kind": _normalise_kind(
                    _lookup(item, "inputKind", "input_kind", default="")
                ),
                "source_type": _sanitise_value(
                    _lookup(item, "sourceType", "source_type")
                ),
                "scene_item_enabled": _sanitise_value(
                    _lookup(item, "sceneItemEnabled", "scene_item_enabled")
                ),
            }
        )
    return output


def _numeric_transform_fields(transform: Mapping[str, Any]) -> dict[str, float]:
    required = (
        ("positionX", "position_x"),
        ("positionY", "position_y"),
        ("scaleX", "scale_x"),
        ("scaleY", "scale_y"),
        ("sourceWidth", "source_width"),
        ("sourceHeight", "source_height"),
    )
    values: dict[str, float] = {}
    for public_name, alternate_name in required:
        value = _lookup(transform, public_name, alternate_name)
        if value is MISSING:
            raise ProbeConfigurationError(
                f"GetSceneItemTransform is missing {public_name}"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ProbeConfigurationError(
                f"GetSceneItemTransform field {public_name} is not numeric"
            ) from exc
        if not math.isfinite(number):
            raise ProbeConfigurationError(
                f"GetSceneItemTransform field {public_name} is not finite"
            )
        values[public_name] = number

    if values["scaleX"] <= 0 or values["scaleY"] <= 0:
        raise ProbeConfigurationError("GetSceneItemTransform scale must be positive")
    if values["sourceWidth"] <= 0 or values["sourceHeight"] <= 0:
        raise ProbeConfigurationError(
            "GetSceneItemTransform source dimensions must be positive"
        )
    return values


def _inspect_connected(
    client: Any,
    host: str,
    port: int,
    *,
    scene_hint: str,
    source_hint: str,
    metadata: Mapping[str, Any],
    password: str = "",
) -> ProbeResult:
    """Read the OBS contract through the production-compatible request API."""

    try:
        get_version = getattr(client, "get_version")
        version_response = get_version()
        version_evidence, websocket_version = _version_evidence(version_response)
    except ProbeConfigurationError as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket responded, but its version/API contract is incompatible.",
            host,
            port,
            details={"phase": "GetVersion", "reason": _safe_text(exc)},
            metadata=metadata,
        )
    except Exception as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket was reachable, but the version handshake/API call failed.",
            host,
            port,
            details=_sanitise_error_details(
                "GetVersion", exc, secrets=(password,)
            ),
            metadata=metadata,
        )

    try:
        if scene_hint:
            scene_name = scene_hint
            scene_selection = "configured"
        else:
            current_scene_response = client.get_current_program_scene()
            scene_name = _lookup(
                current_scene_response, "sceneName", "scene_name", default=MISSING
            )
            if scene_name is MISSING or not str(scene_name).strip():
                raise ProbeConfigurationError(
                    "GetCurrentProgramScene did not return sceneName"
                )
            scene_selection = "current_program_scene"

        scene_items_response = client.get_scene_item_list(scene_name)
        scene_items = _extract_scene_items(scene_items_response)
    except ProbeConfigurationError as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket responded, but GetSceneItemList/API fields do not match the expected contract.",
            host,
            port,
            details={"phase": "GetSceneItemList", "reason": _safe_text(exc)},
            evidence={
                "get_version": version_evidence,
                "scene_selection": scene_selection if "scene_selection" in locals() else "unknown",
            },
            metadata=metadata,
        )
    except Exception as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket was reachable, but GetSceneItemList failed.",
            host,
            port,
            details=_sanitise_error_details(
                "GetSceneItemList", exc, secrets=(password,)
            ),
            evidence={"get_version": version_evidence},
            metadata=metadata,
        )

    item_evidence = _scene_item_evidence(scene_items)
    candidate_indexes: list[int] = []
    selected_index: int | None = None
    for index, item in enumerate(scene_items):
        source_name = _lookup(item, "sourceName", "source_name", default="")
        input_kind = _normalise_kind(
            _lookup(item, "inputKind", "input_kind", default="")
        )
        if source_hint:
            if source_name == source_hint:
                selected_index = index
                break
        elif input_kind in CAPTURE_INPUT_KINDS:
            candidate_indexes.append(index)

    if not source_hint:
        if len(candidate_indexes) == 1:
            selected_index = candidate_indexes[0]
        elif not candidate_indexes:
            return _result(
                TRANSFORM_CONTRACT_FAILED,
                "No supported display/monitor capture source was found in the selected scene.",
                host,
                port,
                details={
                    "phase": "source_selection",
                    "candidate_count": 0,
                    "source_configured": False,
                },
                evidence={
                    "get_version": version_evidence,
                    "get_scene_item_list": {
                        "request": "GetSceneItemList",
                        "scene_selection": scene_selection,
                        "item_count": len(scene_items),
                        "items": item_evidence,
                    },
                },
                metadata=metadata,
            )
        else:
            return _result(
                TRANSFORM_CONTRACT_FAILED,
                "Multiple capture sources were found; configure --source to avoid guessing.",
                host,
                port,
                details={
                    "phase": "source_selection",
                    "candidate_count": len(candidate_indexes),
                    "source_configured": False,
                },
                evidence={
                    "get_version": version_evidence,
                    "get_scene_item_list": {
                        "request": "GetSceneItemList",
                        "scene_selection": scene_selection,
                        "item_count": len(scene_items),
                        "items": item_evidence,
                    },
                },
                metadata=metadata,
            )

    if selected_index is None:
        return _result(
            TRANSFORM_CONTRACT_FAILED,
            "The configured OBS source was not present in the selected scene.",
            host,
            port,
            details={
                "phase": "source_selection",
                "source_configured": True,
                "source_name_exposed": False,
            },
            evidence={
                "get_version": version_evidence,
                "get_scene_item_list": {
                    "request": "GetSceneItemList",
                    "scene_selection": scene_selection,
                    "item_count": len(scene_items),
                    "items": item_evidence,
                },
            },
            metadata=metadata,
        )

    selected_item = scene_items[selected_index]
    item_id = _lookup(selected_item, "sceneItemId", "scene_item_id", default=MISSING)
    source_name = _lookup(selected_item, "sourceName", "source_name", default="")
    scene_input_kind = _normalise_kind(
        _lookup(selected_item, "inputKind", "input_kind", default="")
    )
    if item_id is MISSING or not isinstance(item_id, (int, float)):
        return _result(
            PROTOCOL_API_MISMATCH,
            "The selected scene item does not expose a numeric sceneItemId.",
            host,
            port,
            details={"phase": "GetSceneItemList", "reason": "invalid sceneItemId"},
            evidence={
                "get_version": version_evidence,
                "get_scene_item_list": {
                    "request": "GetSceneItemList",
                    "scene_selection": scene_selection,
                    "item_count": len(scene_items),
                    "items": item_evidence,
                },
            },
            metadata=metadata,
        )

    if scene_input_kind not in CAPTURE_INPUT_KINDS:
        return _result(
            TRANSFORM_CONTRACT_FAILED,
            "The selected OBS source is not a supported display/monitor capture input.",
            host,
            port,
            details={
                "phase": "source_selection",
                "input_kind": scene_input_kind or "<missing>",
            },
            evidence={
                "get_version": version_evidence,
                "get_scene_item_list": {
                    "request": "GetSceneItemList",
                    "scene_selection": scene_selection,
                    "item_count": len(scene_items),
                    "items": item_evidence,
                },
            },
            metadata=metadata,
        )

    try:
        input_response = client.get_input_settings(source_name)
        input_settings = _lookup(
            input_response, "inputSettings", "input_settings", default=MISSING
        )
        if input_settings is MISSING or not isinstance(input_settings, Mapping):
            raise ProbeConfigurationError(
                "GetInputSettings did not return an inputSettings object"
            )
        settings_kind = _normalise_kind(
            _lookup(input_response, "inputKind", "input_kind", default=scene_input_kind)
        )
        monitor_id = _lookup(input_settings, "monitor_id", "monitorId", default=MISSING)
        monitor_id_present = monitor_id not in (MISSING, None, "")
    except ProbeConfigurationError as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket responded, but GetInputSettings/API fields do not match the expected contract.",
            host,
            port,
            details={"phase": "GetInputSettings", "reason": _safe_text(exc)},
            evidence={
                "get_version": version_evidence,
                "get_scene_item_list": {
                    "request": "GetSceneItemList",
                    "scene_selection": scene_selection,
                    "item_count": len(scene_items),
                    "items": item_evidence,
                },
            },
            metadata=metadata,
        )
    except Exception as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket was reachable, but GetInputSettings failed.",
            host,
            port,
            details=_sanitise_error_details(
                "GetInputSettings", exc, secrets=(password,)
            ),
            evidence={"get_version": version_evidence},
            metadata=metadata,
        )

    if settings_kind != scene_input_kind:
        return _result(
            TRANSFORM_CONTRACT_FAILED,
            "The OBS scene item input kind does not match GetInputSettings.",
            host,
            port,
            details={
                "phase": "GetInputSettings",
                "scene_item_input_kind": scene_input_kind,
                "settings_input_kind": settings_kind or "<missing>",
            },
            evidence={
                "get_version": version_evidence,
                "get_input_settings": {
                    "request": "GetInputSettings",
                    "source_label": f"<source-{selected_index + 1}>",
                    "input_kind": settings_kind,
                    "settings": _sanitise_value(input_settings),
                },
            },
            metadata=metadata,
        )

    if scene_input_kind == MONITOR_CAPTURE_KIND and not monitor_id_present:
        return _result(
            TRANSFORM_CONTRACT_FAILED,
            "The Windows monitor_capture source has no monitor_id in GetInputSettings.",
            host,
            port,
            details={
                "phase": "GetInputSettings",
                "input_kind": scene_input_kind,
                "monitor_id_present": False,
            },
            evidence={
                "get_version": version_evidence,
                "get_scene_item_list": {
                    "request": "GetSceneItemList",
                    "scene_selection": scene_selection,
                    "item_count": len(scene_items),
                    "items": item_evidence,
                },
                "get_input_settings": {
                    "request": "GetInputSettings",
                    "source_label": f"<source-{selected_index + 1}>",
                    "input_kind": settings_kind,
                    "monitor_id_present": False,
                    "settings": _sanitise_value(input_settings),
                },
            },
            metadata=metadata,
        )

    try:
        transform_response = client.get_scene_item_transform(scene_name, item_id)
        transform = _lookup(
            transform_response,
            "sceneItemTransform",
            "scene_item_transform",
            default=MISSING,
        )
        if transform is MISSING or not isinstance(transform, Mapping):
            raise ProbeConfigurationError(
                "GetSceneItemTransform did not return a sceneItemTransform object"
            )
        numeric_transform = _numeric_transform_fields(transform)
    except ProbeConfigurationError as exc:
        return _result(
            TRANSFORM_CONTRACT_FAILED,
            "OBS responded, but the selected source does not satisfy the transform contract.",
            host,
            port,
            details={"phase": "GetSceneItemTransform", "reason": _safe_text(exc)},
            evidence={
                "get_version": version_evidence,
                "get_scene_item_list": {
                    "request": "GetSceneItemList",
                    "scene_selection": scene_selection,
                    "item_count": len(scene_items),
                    "items": item_evidence,
                },
                "get_input_settings": {
                    "request": "GetInputSettings",
                    "source_label": f"<source-{selected_index + 1}>",
                    "input_kind": settings_kind,
                    "monitor_id_present": monitor_id_present,
                    "settings": _sanitise_value(input_settings),
                },
            },
            metadata=metadata,
        )
    except Exception as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "OBS WebSocket was reachable, but GetSceneItemTransform failed.",
            host,
            port,
            details=_sanitise_error_details(
                "GetSceneItemTransform", exc, secrets=(password,)
            ),
            evidence={"get_version": version_evidence},
            metadata=metadata,
        )

    transform_evidence = {
        "request": "GetSceneItemTransform",
        "source_label": f"<source-{selected_index + 1}>",
        "required_numeric_fields": numeric_transform,
        "all_returned_fields": _sanitise_value(transform),
    }
    evidence = {
        "get_version": version_evidence,
        "get_scene_item_list": {
            "request": "GetSceneItemList",
            "scene_selection": scene_selection,
            "item_count": len(scene_items),
            "items": item_evidence,
        },
        "get_input_settings": {
            "request": "GetInputSettings",
            "source_label": f"<source-{selected_index + 1}>",
            "input_kind": settings_kind,
            "monitor_id_present": monitor_id_present,
            "settings": _sanitise_value(input_settings),
        },
        "get_scene_item_transform": transform_evidence,
    }
    return _result(
        SUCCESS,
        "OBS transform contract verified with read-only requests.",
        host,
        port,
        details={
            "protocol": "obs-websocket-5.x",
            "scene_selection": scene_selection,
            "input_kind": scene_input_kind,
            "monitor_id_present": monitor_id_present,
            "transform_fields_verified": sorted(numeric_transform),
        },
        evidence=evidence,
        metadata=metadata,
    )


def inspect_obs_contract(
    host: str,
    port: int,
    password: str,
    *,
    scene_hint: str = "",
    source_hint: str = "",
    timeout: float = 2.0,
    client_factory: Callable[..., Any] | None = None,
    endpoint_probe: Callable[[str, int, float], EndpointCheck] = check_tcp_endpoint,
    installation_detector: Callable[[], ObsInstallation] = detect_obs_installation,
    metadata: Mapping[str, Any] | None = None,
) -> ProbeResult:
    """Run the read-only contract probe with injectable seams for tests."""

    endpoint = endpoint_probe(host, port, timeout)
    if not endpoint.reachable:
        installation = installation_detector()
        installation_details = {
            "installed": installation.installed,
            "running": installation.running,
            "detection_method": installation.detection_method,
            "tcp_error_type": endpoint.error_type,
        }
        if installation.installed is False and installation.running is not True:
            status = MISSING_OBS
            summary = (
                "OBS was not detected and the local WebSocket endpoint is unreachable."
            )
        else:
            status = UNREACHABLE_ENDPOINT
            summary = (
                "OBS WebSocket endpoint is unreachable; OBS may be stopped or its server disabled."
            )
        return _result(
            status,
            summary,
            host,
            port,
            details={"phase": "tcp_connect", "installation": installation_details},
            metadata=metadata,
        )

    if client_factory is None:
        try:
            client_factory = _load_req_client()
        except ModuleNotFoundError as exc:
            return _result(
                PROBE_DEPENDENCY_MISSING,
                "The OBS endpoint is reachable, but obsws-python is unavailable in this environment.",
                host,
                port,
                details={"phase": "dependency_import", "error": _safe_error(exc)},
                metadata=metadata,
            )

    try:
        client = client_factory(host=host, port=port, password=password)
    except (ConnectionRefusedError, TimeoutError, socket.timeout) as exc:
        return _result(
            UNREACHABLE_ENDPOINT,
            "The OBS endpoint stopped accepting connections during the probe.",
            host,
            port,
            details=_sanitise_error_details(
                "websocket_connect", exc, secrets=(password,)
            ),
            metadata=metadata,
        )
    except Exception as exc:
        return _result(
            PROTOCOL_API_MISMATCH,
            "TCP accepted a connection, but the OBS WebSocket handshake/API was not usable.",
            host,
            port,
            details=_sanitise_error_details(
                "websocket_connect", exc, secrets=(password,)
            ),
            metadata=metadata,
        )

    try:
        return _inspect_connected(
            client,
            host,
            port,
            scene_hint=scene_hint,
            source_hint=source_hint,
            metadata=metadata or {},
            password=password,
        )
    finally:
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            try:
                disconnect()
            except Exception:
                # Disconnect is cleanup only.  Never replace the diagnostic
                # result with a potentially noisy cleanup exception.
                pass


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError as exc:
        raise ProbeConfigurationError(
            "TOML config reading requires Python 3.11+; use OBS_WEBSOCKET_PASSWORD "
            "with the current interpreter"
        ) from exc

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ProbeConfigurationError("cannot read the requested config file") from exc
    except Exception as exc:
        raise ProbeConfigurationError("config file is not valid TOML") from exc
    if not isinstance(data, dict):
        raise ProbeConfigurationError("config file did not contain a TOML table")
    return data


def _resolve_options(args: argparse.Namespace) -> dict[str, Any]:
    data: dict[str, Any] = {}
    config_provided = args.config is not None
    if args.config is not None:
        data = _load_toml(args.config)
    obs_data = data.get("obs", {})
    if not isinstance(obs_data, Mapping):
        raise ProbeConfigurationError("[obs] must be a TOML table")

    host = args.host if args.host is not None else obs_data.get("host", "127.0.0.1")
    port = args.port if args.port is not None else obs_data.get("port", 4455)
    scene = args.scene if args.scene is not None else obs_data.get("scene", "")
    source = args.source if args.source is not None else obs_data.get("source", "")
    if not isinstance(host, str) or not host.strip():
        raise ProbeConfigurationError("host must be a non-empty string")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise ProbeConfigurationError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ProbeConfigurationError("port must be between 1 and 65535")
    if not isinstance(scene, str) or not isinstance(source, str):
        raise ProbeConfigurationError("scene and source must be strings")
    if not ENV_NAME_RE.fullmatch(args.password_env):
        raise ProbeConfigurationError("password environment variable name is invalid")

    env_value = os.environ.get(args.password_env)
    if env_value is not None:
        password = env_value
        password_source = "environment"
    else:
        config_password = obs_data.get("password", "")
        if config_password is None:
            config_password = ""
        if not isinstance(config_password, str):
            raise ProbeConfigurationError("[obs].password must be a string")
        password = config_password
        password_source = "config" if config_password else "empty"

    return {
        "host": host.strip(),
        "port": port,
        "scene": scene,
        "source": source,
        "password": password,
        "password_source": password_source,
        "config_provided": config_provided,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only OBS WebSocket contract probe. Passwords are accepted via "
            "OBS_WEBSOCKET_PASSWORD (or --password-env) or --config, never as a CLI argument."
        )
    )
    parser.add_argument("--config", type=Path, help="Optional TOML config containing [obs] settings.")
    parser.add_argument("--host", help="OBS WebSocket host (default: 127.0.0.1 or config value).")
    parser.add_argument("--port", type=int, help="OBS WebSocket port (default: 4455 or config value).")
    parser.add_argument("--scene", help="Scene name; otherwise use the current program scene.")
    parser.add_argument(
        "--source",
        help="Exact source name; required when more than one capture source exists.",
    )
    parser.add_argument(
        "--password-env",
        default="OBS_WEBSOCKET_PASSWORD",
        help="Environment variable containing the WebSocket password (default: OBS_WEBSOCKET_PASSWORD).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="TCP reachability timeout in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write sanitized JSON evidence to this path; existing files are not overwritten by default.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing --output file.",
    )
    parser.add_argument("--json", action="store_true", help="Print the sanitized result as JSON.")
    return parser


def _write_evidence(path: Path, payload: Mapping[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _print_result(result: ProbeResult, *, output: Path | None, as_json: bool) -> None:
    payload = result.as_payload()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"status: {result.status}")
    print(f"summary: {result.summary}")
    print(f"endpoint: {result.endpoint['host']}:{result.endpoint['port']}")
    if result.details.get("input_kind"):
        print(f"input_kind: {result.details['input_kind']}")
    if "monitor_id_present" in result.details:
        print(f"monitor_id_present: {result.details['monitor_id_present']}")
    if output is not None:
        print(f"evidence: {output}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        parser.error("--timeout must be a positive finite number")

    try:
        options = _resolve_options(args)
    except ProbeConfigurationError as exc:
        result = _result(
            INVALID_CONFIGURATION,
            "Probe options are invalid; no OBS connection was attempted.",
            "<not-resolved>",
            0,
            details={"phase": "configuration", "reason": _safe_text(exc)},
            metadata={"password_value_exposed": False},
        )
        _print_result(result, output=None, as_json=args.json)
        return result.exit_code

    metadata = {
        "password_supplied": bool(options["password"]),
        "password_source": options["password_source"],
        "password_value_exposed": False,
        "config_provided": options["config_provided"],
        "scene_configured": bool(options["scene"]),
        "source_configured": bool(options["source"]),
        "read_only_requests": [
            "GetVersion",
            "GetCurrentProgramScene",
            "GetSceneItemList",
            "GetInputSettings",
            "GetSceneItemTransform",
        ],
    }
    result = inspect_obs_contract(
        options["host"],
        options["port"],
        options["password"],
        scene_hint=options["scene"],
        source_hint=options["source"],
        timeout=args.timeout,
        metadata=metadata,
    )
    payload = result.as_payload()

    if args.output is not None:
        try:
            _write_evidence(args.output, payload, overwrite=args.overwrite)
        except OSError as exc:
            write_result = _result(
                EVIDENCE_WRITE_FAILED,
                "The probe result was not written to the requested evidence path.",
                options["host"],
                options["port"],
                details={"phase": "write_evidence", "error": _safe_error(exc)},
                metadata={"password_value_exposed": False},
            )
            _print_result(write_result, output=None, as_json=args.json)
            return write_result.exit_code

    _print_result(result, output=args.output, as_json=args.json)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
