from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict


def read_text_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def read_int_file(path: str) -> int | None:
    raw = read_text_file(path)
    if raw in (None, "", "max"):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def percent(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round((float(numerator) / float(denominator)) * 100.0, 2)


def host_memory_snapshot() -> Dict[str, Any]:
    values: Dict[str, int] = {}
    raw = read_text_file("/proc/meminfo")
    if raw:
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            number = rest.strip().split()[0] if rest.strip() else ""
            if number.isdigit():
                values[key] = int(number) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    used = total - available if total is not None and available is not None else None
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "used_percent": percent(used, total),
    }


def container_memory_snapshot() -> Dict[str, Any]:
    current = read_int_file("/sys/fs/cgroup/memory.current")
    limit = read_int_file("/sys/fs/cgroup/memory.max")
    if current is None:
        current = read_int_file("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if limit is None:
        limit = read_int_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if limit is not None and limit > 1 << 60:
        limit = None
    return {
        "used_bytes": current,
        "limit_bytes": limit,
        "used_percent": percent(current, limit),
    }


def disk_snapshot(path: Path, fallback: Path) -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        usage = shutil.disk_usage(fallback)
    used = int(usage.total - usage.free)
    return {
        "path": str(path),
        "total_bytes": int(usage.total),
        "used_bytes": used,
        "free_bytes": int(usage.free),
        "used_percent": percent(used, int(usage.total)),
    }


def system_status_payload(
    *,
    root_dir: Path,
    started_at: float,
    persistence: Any,
    job_store: Any,
    production_mode: Callable[[], bool],
    default_persistence_path: Callable[[Path], Path],
) -> Dict[str, Any]:
    schema = persistence.schema_info()
    db_path = Path(str(schema.get("path") or default_persistence_path(root_dir)))
    data_path = db_path.parent if db_path.parent.exists() else root_dir / "data"
    try:
        db_size = db_path.stat().st_size
    except OSError:
        db_size = None
    return {
        "ok": True,
        "checked_at": time.time(),
        "api": {
            "uptime_seconds": round(time.time() - started_at, 2),
            "production": production_mode(),
            "domain": os.environ.get("PLANORA_DOMAIN", ""),
            "public_base_url": os.environ.get("PLANORA_PUBLIC_BASE_URL", ""),
        },
        "database": {**schema, "size_bytes": db_size},
        "disk": disk_snapshot(data_path, root_dir),
        "memory": {
            "container": container_memory_snapshot(),
            "host": host_memory_snapshot(),
        },
        "jobs": job_store.stats(),
        "limits": {
            "anonymous_rate_per_minute": int(os.environ.get("PLANORA_RATE_LIMIT_ANONYMOUS_PER_MINUTE", "120")),
            "authenticated_rate_per_minute": int(os.environ.get("PLANORA_RATE_LIMIT_AUTHENTICATED_PER_MINUTE", "1200")),
            "auth_rate_per_minute": int(os.environ.get("PLANORA_RATE_LIMIT_AUTH_PER_MINUTE", "20")),
            "telemetry_rate_per_minute": int(os.environ.get("PLANORA_RATE_LIMIT_TELEMETRY_PER_MINUTE", "600")),
            "max_request_bytes": int(os.environ.get("PLANORA_MAX_REQUEST_BYTES", str(20 * 1024 * 1024))),
        },
        "netdata": {
            "url": os.environ.get("PLANORA_NETDATA_URL", ""),
            "note": "Use Netdata Cloud for detailed host and Docker metrics.",
        },
    }
