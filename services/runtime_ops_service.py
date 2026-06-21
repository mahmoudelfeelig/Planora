from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import traceback
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_RUNTIME_SETTINGS: Dict[str, Any] = {
    "crash_reports_opt_in": False,
    "telemetry_opt_in": False,
    "update_channel": "stable",
    "update_manifest_path": "docs/portal/update_manifest.json",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_runtime_paths(app_name: str = "planora") -> Dict[str, str]:
    root = Path(os.path.expanduser("~")) / f".{str(app_name).lower()}"
    logs = root / "logs"
    crash = root / "crash_reports"
    telemetry = root / "telemetry"
    support = root / "support"
    try:
        logs.mkdir(parents=True, exist_ok=True)
        crash.mkdir(parents=True, exist_ok=True)
        telemetry.mkdir(parents=True, exist_ok=True)
        support.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path(tempfile.gettempdir()) / f".{str(app_name).lower()}"
        logs = root / "logs"
        crash = root / "crash_reports"
        telemetry = root / "telemetry"
        support = root / "support"
        logs.mkdir(parents=True, exist_ok=True)
        crash.mkdir(parents=True, exist_ok=True)
        telemetry.mkdir(parents=True, exist_ok=True)
        support.mkdir(parents=True, exist_ok=True)
    return {
        "root": str(root),
        "settings": str(root / "runtime_settings.json"),
        "runtime_log": str(logs / "runtime.jsonl"),
        "crash_dir": str(crash),
        "telemetry_log": str(telemetry / "telemetry.jsonl"),
        "support_dir": str(support),
    }


def load_runtime_settings(path: str | Path) -> Dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return dict(DEFAULT_RUNTIME_SETTINGS)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Runtime settings must be a JSON object.")
    merged = dict(DEFAULT_RUNTIME_SETTINGS)
    merged.update(payload)
    return merged


def save_runtime_settings(path: str | Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_RUNTIME_SETTINGS)
    merged.update(dict(settings or {}))
    Path(path).write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
    return merged


def append_runtime_log(
    path: str | Path,
    *,
    event: str,
    level: str = "info",
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    row = {
        "timestamp_utc": _utc_now(),
        "level": str(level),
        "event": str(event),
        "details": dict(details or {}),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def record_telemetry_event(
    path: str | Path,
    *,
    event: str,
    details: Dict[str, Any] | None = None,
    opt_in: bool = False,
) -> Dict[str, Any] | None:
    if not bool(opt_in):
        return None
    return append_runtime_log(path, event=event, level="telemetry", details=details)


def write_crash_report(
    crash_dir: str | Path,
    *,
    error_type: str,
    message: str,
    traceback_text: str = "",
    context: Dict[str, Any] | None = None,
    opt_in: bool = False,
) -> str | None:
    if not bool(opt_in):
        return None
    target_dir = Path(crash_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"crash_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    payload = {
        "timestamp_utc": _utc_now(),
        "error_type": str(error_type),
        "message": str(message),
        "traceback": str(traceback_text),
        "context": dict(context or {}),
        "platform": platform.platform(),
        "python": sys.version,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(version or "").replace("-", ".").split("."):
        try:
            parts.append(int(chunk))
        except Exception:
            parts.append(0)
    return tuple(parts)


def save_update_manifest(path: str | Path, payload: Dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(dict(payload or {}), indent=2), encoding="utf-8")


def load_update_manifest(source: str | Path) -> Dict[str, Any]:
    text: str
    source_text = str(source)
    if source_text.startswith(("http://", "https://")):
        with urllib.request.urlopen(source_text, timeout=10) as response:  # nosec B310
            text = response.read().decode("utf-8")
    else:
        text = Path(source).read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Update manifest must be a JSON object.")
    return payload


def check_for_updates(
    *,
    current_version: str,
    manifest_source: str | Path,
    channel: str = "stable",
) -> Dict[str, Any]:
    manifest = load_update_manifest(manifest_source)
    channels = dict(manifest.get("channels", {}) or {})
    release = dict(channels.get(str(channel), {}) or {})
    latest = str(release.get("version", current_version))
    available = _version_key(latest) > _version_key(current_version)
    return {
        "channel": str(channel),
        "current_version": str(current_version),
        "latest_version": latest,
        "available": bool(available),
        "download_url": str(release.get("download_url", "")),
        "notes": str(release.get("notes", "")),
    }


def collect_support_bundle(
    out_path: str | Path,
    *,
    runtime_paths: Dict[str, str],
    settings: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
    extra_files: Dict[str, str] | None = None,
) -> str:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at_utc": _utc_now(),
        "platform": platform.platform(),
        "python": sys.version,
        "metadata": dict(metadata or {}),
        "settings": dict(settings or {}),
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        for name, path in dict(runtime_paths or {}).items():
            p = Path(path)
            if p.is_file():
                archive.write(p, arcname=f"runtime/{name}{p.suffix or '.txt'}")
            elif p.is_dir():
                for child in sorted(p.rglob("*")):
                    if child.is_file():
                        archive.write(
                            child,
                            arcname=f"runtime/{name}/{child.relative_to(p)}",
                        )
        for arcname, content in dict(extra_files or {}).items():
            archive.writestr(str(arcname), str(content))
    return str(target)


def crash_context_from_exception(exc: BaseException) -> Dict[str, Any]:
    return {
        "error_type": exc.__class__.__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
