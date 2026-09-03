from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.application_service import SessionStore, run_workspace_action
from services.timetable_import_service import import_timetable_csv
from utils.generator import generate_instance, instance_to_json
from utils.io import instance_from_json
from utils.process_memory import peak_rss_kib
from utils.specs import validate_schedule_against_instance


RESULT_MARKER = "PLANORA_E2E_BENCHMARK_RESULT="
_HTTP_PRESET_DEFAULT_SEEDS = {
    "small_demo": 1,
    "mixed_large": 2,
    "block_profs": 3,
    "labs_only": 4,
    "ss23_uni_like": 2023,
    "uni_like": 2023,
    "target_case": 42,
    "giu": 42,
    "giu_target": 42,
}

_WORKLOAD_LABELS = {
    "ss23_uni_like": "Spring 2023 calibrated university scenario",
    "target_case": "SS23-calibrated synthetic GIU-scale proxy",
    "giu_target": "SS23-calibrated synthetic GIU-scale proxy with historical policy",
}


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    return call(), float(time.perf_counter() - started)


def _json_roundtrip(payload: Any) -> tuple[Any, float, float, int]:
    encoded, encode_seconds = _timed(
        lambda: json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    )
    decoded, decode_seconds = _timed(lambda: json.loads(encoded.decode("utf-8")))
    return decoded, encode_seconds, decode_seconds, len(encoded)


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _solve_payload(
    *,
    room_mode: str,
    objective_profile: str,
    solve_seconds: float,
    workers: int,
    seed: int,
) -> dict[str, Any]:
    return {
        "options": {
            "room_mode": str(room_mode),
            "objective_profile": str(objective_profile),
            "use_objective": False,
            "retry_without_objective": False,
            "time_limit_seconds": float(solve_seconds),
            "workers": int(workers),
            "random_seed": int(seed),
        }
    }


def _improve_payload(*, iterations: int, improve_seconds: float) -> dict[str, Any]:
    return {
        "options": {
            "iterations": int(iterations),
            "max_seconds": float(improve_seconds),
            "progress_every": max(1, min(25, int(iterations) // 100 or 1)),
        }
    }


def _load_embedded_source(
    *, mode: str, seed: int, import_csv: str | Path | None
) -> tuple[dict[str, Any], dict[int, dict[str, Any]], dict[str, Any]]:
    if import_csv is not None:
        inst, schedule, meta = import_timetable_csv(import_csv, lock_imported=False)
        return (
            instance_to_json(inst),
            schedule,
            {
                "kind": "csv_import",
                "path": str(Path(import_csv)),
                "import_meta": dict(meta or {}),
            },
        )
    inst = generate_instance(str(mode), seed=int(seed))
    return (
        instance_to_json(inst),
        {},
        {
            "kind": "built_in_generator",
            "mode": str(mode),
            "seed": int(seed),
        },
    )


def run_embedded_workflow(
    *,
    mode: str = "target_case",
    seed: int = 42,
    import_csv: str | Path | None = None,
    room_mode: str = "partitioned",
    objective_profile: str = "university_fast",
    solve_seconds: float = 15.0,
    workers: int = 4,
    improve_iterations: int = 500,
    improve_seconds: float = 2.0,
) -> dict[str, Any]:
    """Measure the embedded product path through the shared session/action service."""
    workflow_started = time.perf_counter()
    stages: dict[str, float] = {}
    sizes: dict[str, int] = {}

    source, stages["source_generate_or_import"] = _timed(
        lambda: _load_embedded_source(
            mode=str(mode), seed=int(seed), import_csv=import_csv
        )
    )
    instance_json, initial_schedule, source_meta = source
    request, encode_seconds, decode_seconds, request_bytes = _json_roundtrip(
        {
            "instance": instance_json,
            "schedule": initial_schedule,
            "meta": {"source": "controlled-e2e-benchmark"},
        }
    )
    stages["session_request_encode"] = encode_seconds
    stages["session_request_decode"] = decode_seconds
    sizes["session_request_bytes"] = int(request_bytes)

    store = SessionStore()
    session, stages["session_create"] = _timed(
        lambda: store.create(
            instance_json=dict(request["instance"]),
            schedule=dict(request.get("schedule") or {}),
            meta=dict(request.get("meta") or {}),
        )
    )

    solve_request = _solve_payload(
        room_mode=room_mode,
        objective_profile=objective_profile,
        solve_seconds=solve_seconds,
        workers=workers,
        seed=seed,
    )
    solve_result, stages["solve_action"] = _timed(
        lambda: run_workspace_action(
            instance_json=session.instance_json,
            schedule=session.schedule,
            action="solve",
            payload=solve_request,
        )
    )
    solve_result, encode_seconds, decode_seconds, response_bytes = _json_roundtrip(
        solve_result
    )
    stages["solve_response_encode"] = encode_seconds
    stages["solve_response_decode"] = decode_seconds
    sizes["solve_response_bytes"] = int(response_bytes)

    raw_status = int(solve_result.get("raw_status", solve_result.get("status", -1)))
    solved_schedule = dict(solve_result.get("schedule") or {})
    solve_feasible = raw_status in {2, 4} and bool(solved_schedule)
    if solve_feasible:
        session = store.update(session.session_id, schedule=solved_schedule)

    validation_errors: list[str] = []
    score: dict[str, Any] = {}
    improve_result: dict[str, Any] | None = None
    final_score: dict[str, Any] = {}
    if solve_feasible:
        inst = instance_from_json(session.instance_json)
        validation_errors, stages["independent_solve_validation"] = _timed(
            lambda: validate_schedule_against_instance(
                inst,
                session.schedule,
                strict_rooms=True,
                require_all_activities=True,
            )
        )
        score, stages["solve_score_action"] = _timed(
            lambda: run_workspace_action(
                instance_json=session.instance_json,
                schedule=session.schedule,
                action="score",
                payload={},
            )
        )
        score, encode_seconds, decode_seconds, response_bytes = _json_roundtrip(score)
        stages["solve_score_response_encode"] = encode_seconds
        stages["solve_score_response_decode"] = decode_seconds
        sizes["solve_score_response_bytes"] = int(response_bytes)

        improve_result, stages["improve_action"] = _timed(
            lambda: run_workspace_action(
                instance_json=session.instance_json,
                schedule=session.schedule,
                action="improve",
                payload=_improve_payload(
                    iterations=improve_iterations,
                    improve_seconds=improve_seconds,
                ),
            )
        )
        improve_result, encode_seconds, decode_seconds, response_bytes = (
            _json_roundtrip(improve_result)
        )
        stages["improve_response_encode"] = encode_seconds
        stages["improve_response_decode"] = decode_seconds
        sizes["improve_response_bytes"] = int(response_bytes)
        improved_schedule = dict(improve_result.get("schedule") or {})
        if improved_schedule:
            session = store.update(session.session_id, schedule=improved_schedule)

        final_validation, stages["independent_improve_validation"] = _timed(
            lambda: validate_schedule_against_instance(
                inst,
                session.schedule,
                strict_rooms=True,
                require_all_activities=True,
            )
        )
        validation_errors.extend(final_validation)
        final_score, stages["improve_score_action"] = _timed(
            lambda: run_workspace_action(
                instance_json=session.instance_json,
                schedule=session.schedule,
                action="score",
                payload={},
            )
        )
        final_score, encode_seconds, decode_seconds, response_bytes = _json_roundtrip(
            final_score
        )
        stages["improve_score_response_encode"] = encode_seconds
        stages["improve_score_response_decode"] = decode_seconds
        sizes["improve_score_response_bytes"] = int(response_bytes)

    total_seconds = float(time.perf_counter() - workflow_started)
    return {
        "schema_version": 1,
        "kind": "planora_controlled_end_to_end_performance",
        "transport": "embedded",
        "source": source_meta,
        "configuration": {
            "room_mode": str(room_mode),
            "objective_profile": str(objective_profile),
            "solve_seconds": float(solve_seconds),
            "workers": int(workers),
            "seed": int(seed),
            "improve_iterations": int(improve_iterations),
            "improve_seconds": float(improve_seconds),
        },
        "instance": {
            "activities": int(len(instance_json.get("activities") or {})),
            "rooms": int(len(instance_json.get("rooms") or {})),
            "fingerprint_sha256": _sha256_json(instance_json),
            "workload_label": _WORKLOAD_LABELS.get(str(mode), str(mode)),
        },
        "solve": {
            "feasible": bool(solve_feasible),
            "status": int(solve_result.get("status", -1)),
            "raw_status": int(raw_status),
            "schedule_rows": int(len(solved_schedule)),
            "hard_conflicts": list(solve_result.get("hard_conflicts") or []),
            "engine_meta": dict(solve_result.get("meta") or {}),
        },
        "improve": {
            "completed": improve_result is not None,
            "before_soft_penalty": (
                None
                if improve_result is None
                else int(
                    dict(improve_result.get("before") or {}).get("soft_penalty", 0)
                )
            ),
            "after_soft_penalty": (
                None
                if improve_result is None
                else int(dict(improve_result.get("after") or {}).get("soft_penalty", 0))
            ),
        },
        "validation_error_count": int(len(validation_errors)),
        "validation_errors": validation_errors[:20],
        "solve_score": score,
        "final_score": final_score,
        "stage_seconds": stages,
        "measured_total_seconds": total_seconds,
        "payload_sizes": sizes,
        "peak_rss_kib": peak_rss_kib(),
        "valid": bool(
            solve_feasible
            and not validation_errors
            and improve_result is not None
            and int(final_score.get("hard_conflict_count", -1)) == 0
        ),
    }


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_headers() -> dict[str, str]:
    token = str(os.environ.get("PLANORA_BENCHMARK_TOKEN", "") or "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {
        "X-Planora-User": "performance-runner",
        "X-Planora-Role": "admin",
        "X-Planora-Tenant": "benchmark",
    }


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[dict[str, Any], int]:
    body = None
    headers = _http_headers()
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:  # nosec B310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"Expected an object response from {url}")
    return decoded, len(raw)


@contextmanager
def _http_api(base_url: str | None) -> Iterator[tuple[str, float]]:
    if base_url:
        yield str(base_url).rstrip("/"), 0.0
        return

    port = _find_free_port()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="planora-e2e-http-") as tmp:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(env.get("PYTHONPATH", ""))])
        env["PLANORA_DB_PATH"] = str(Path(tmp) / "benchmark.sqlite3")
        env["PLANORA_TRUST_DEV_HEADERS"] = "1"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "api.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 20.0
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"Benchmark API exited during startup with code {proc.returncode}"
                    )
                try:
                    _http_json("GET", f"{url}/health", timeout=1.0)
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Benchmark API did not become ready in 20 seconds"
                        )
                    time.sleep(0.1)
            yield url, float(time.perf_counter() - started)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)


def run_http_workflow(
    *,
    mode: str = "target_case",
    seed: int = 42,
    import_csv: str | Path | None = None,
    room_mode: str = "partitioned",
    objective_profile: str = "university_fast",
    solve_seconds: float = 15.0,
    workers: int = 4,
    improve_iterations: int = 500,
    improve_seconds: float = 2.0,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Measure the real HTTP preset/import and session action contract."""
    workflow_started = time.perf_counter()
    stages: dict[str, float] = {}
    sizes: dict[str, int] = {}
    with _http_api(base_url) as (api_url, startup_seconds):
        stages["http_server_startup"] = float(startup_seconds)
        preset_seed = _HTTP_PRESET_DEFAULT_SEEDS.get(str(mode))
        if import_csv is None and preset_seed == int(seed):
            source_url = f"{api_url}/preset/{urllib.parse.quote(str(mode))}"
            source, stages["source_generate_http"] = _timed(
                lambda: _http_json("GET", source_url, timeout=30.0)
            )
            source_payload, source_bytes = source
            instance_json = dict(source_payload.get("instance") or {})
            initial_schedule: dict[str, Any] = {}
            source_meta = {
                "kind": "http_builtin_generator",
                "mode": str(mode),
                "seed": int(preset_seed),
            }
        elif import_csv is None:
            # The current preset endpoint intentionally exposes canonical data and
            # does not accept a seed. Build custom-seed inputs in this benchmark
            # process, then send the exact instance through the same HTTP session
            # and action contract so the measured case cannot silently drift.
            generated, stages["source_generate_client"] = _timed(
                lambda: instance_to_json(generate_instance(str(mode), seed=int(seed)))
            )
            instance_json = dict(generated)
            initial_schedule = {}
            source_payload, _, _, source_bytes = _json_roundtrip(
                {"mode": str(mode), "seed": int(seed), "instance": instance_json}
            )
            instance_json = dict(source_payload.get("instance") or {})
            source_meta = {
                "kind": "client_generator_http_actions",
                "mode": str(mode),
                "seed": int(seed),
                "reason": "preset_endpoint_has_canonical_seed_only",
            }
        else:
            csv_path = Path(import_csv)
            import_request = {
                "filename": csv_path.name,
                "content": csv_path.read_text(encoding="utf-8-sig"),
                "lock_imported": False,
            }
            source, stages["source_import_http"] = _timed(
                lambda: _http_json(
                    "POST",
                    f"{api_url}/import/csv",
                    payload=import_request,
                    timeout=60.0,
                )
            )
            source_payload, source_bytes = source
            instance_json = dict(source_payload.get("instance") or {})
            initial_schedule = dict(source_payload.get("schedule") or {})
            source_meta = {"kind": "http_csv_import", "path": str(csv_path)}
        sizes["source_response_bytes"] = int(source_bytes)

        session_response, stages["session_create_http"] = _timed(
            lambda: _http_json(
                "POST",
                f"{api_url}/sessions",
                payload={
                    "instance": instance_json,
                    "schedule": initial_schedule,
                    "meta": {"source": "controlled-e2e-benchmark"},
                },
                timeout=60.0,
            )
        )
        session_payload, session_bytes = session_response
        sizes["session_response_bytes"] = int(session_bytes)
        session_id = str(session_payload["session_id"])

        solve_response, stages["solve_http_roundtrip"] = _timed(
            lambda: _http_json(
                "POST",
                f"{api_url}/sessions/{session_id}/solve",
                payload=_solve_payload(
                    room_mode=room_mode,
                    objective_profile=objective_profile,
                    solve_seconds=solve_seconds,
                    workers=workers,
                    seed=seed,
                ),
                timeout=float(solve_seconds) + 60.0,
            )
        )
        solve_envelope, solve_bytes = solve_response
        sizes["solve_response_bytes"] = int(solve_bytes)
        solve_result = dict(solve_envelope.get("result") or {})
        raw_status = int(solve_result.get("raw_status", solve_result.get("status", -1)))
        solved_schedule = dict(solve_result.get("schedule") or {})
        solve_feasible = raw_status in {2, 4} and bool(solved_schedule)

        validation_errors: list[str] = []
        score: dict[str, Any] = {}
        improve_result: dict[str, Any] | None = None
        final_score: dict[str, Any] = {}
        if solve_feasible:
            inst = instance_from_json(instance_json)
            validation_errors, stages["independent_solve_validation"] = _timed(
                lambda: validate_schedule_against_instance(
                    inst,
                    solved_schedule,
                    strict_rooms=True,
                    require_all_activities=True,
                )
            )
            score_response, stages["solve_score_http_roundtrip"] = _timed(
                lambda: _http_json(
                    "POST",
                    f"{api_url}/sessions/{session_id}/score",
                    payload={},
                    timeout=60.0,
                )
            )
            score_envelope, score_bytes = score_response
            sizes["solve_score_response_bytes"] = int(score_bytes)
            score = dict(score_envelope.get("result") or {})

            improve_response, stages["improve_http_roundtrip"] = _timed(
                lambda: _http_json(
                    "POST",
                    f"{api_url}/sessions/{session_id}/improve",
                    payload=_improve_payload(
                        iterations=improve_iterations,
                        improve_seconds=improve_seconds,
                    ),
                    timeout=float(improve_seconds) + 60.0,
                )
            )
            improve_envelope, improve_bytes = improve_response
            sizes["improve_response_bytes"] = int(improve_bytes)
            improve_result = dict(improve_envelope.get("result") or {})
            improved_schedule = dict(improve_result.get("schedule") or {})

            final_validation, stages["independent_improve_validation"] = _timed(
                lambda: validate_schedule_against_instance(
                    inst,
                    improved_schedule,
                    strict_rooms=True,
                    require_all_activities=True,
                )
            )
            validation_errors.extend(final_validation)
            final_score_response, stages["improve_score_http_roundtrip"] = _timed(
                lambda: _http_json(
                    "POST",
                    f"{api_url}/sessions/{session_id}/score",
                    payload={},
                    timeout=60.0,
                )
            )
            final_score_envelope, final_score_bytes = final_score_response
            sizes["improve_score_response_bytes"] = int(final_score_bytes)
            final_score = dict(final_score_envelope.get("result") or {})

    total_seconds = float(time.perf_counter() - workflow_started)
    return {
        "schema_version": 1,
        "kind": "planora_controlled_end_to_end_performance",
        "transport": "http",
        "source": source_meta,
        "configuration": {
            "room_mode": str(room_mode),
            "objective_profile": str(objective_profile),
            "solve_seconds": float(solve_seconds),
            "workers": int(workers),
            "seed": int(seed),
            "improve_iterations": int(improve_iterations),
            "improve_seconds": float(improve_seconds),
            "self_hosted_api": not bool(base_url),
        },
        "instance": {
            "activities": int(len(instance_json.get("activities") or {})),
            "rooms": int(len(instance_json.get("rooms") or {})),
            "fingerprint_sha256": _sha256_json(instance_json),
            "workload_label": _WORKLOAD_LABELS.get(str(mode), str(mode)),
        },
        "solve": {
            "feasible": bool(solve_feasible),
            "status": int(solve_result.get("status", -1)),
            "raw_status": int(raw_status),
            "schedule_rows": int(len(solved_schedule)),
            "hard_conflicts": list(solve_result.get("hard_conflicts") or []),
            "engine_meta": dict(solve_result.get("meta") or {}),
        },
        "improve": {
            "completed": improve_result is not None,
            "before_soft_penalty": (
                None
                if improve_result is None
                else int(
                    dict(improve_result.get("before") or {}).get("soft_penalty", 0)
                )
            ),
            "after_soft_penalty": (
                None
                if improve_result is None
                else int(dict(improve_result.get("after") or {}).get("soft_penalty", 0))
            ),
        },
        "validation_error_count": int(len(validation_errors)),
        "validation_errors": validation_errors[:20],
        "solve_score": score,
        "final_score": final_score,
        "stage_seconds": stages,
        "measured_total_seconds": total_seconds,
        "payload_sizes": sizes,
        "peak_rss_kib": peak_rss_kib(),
        "valid": bool(
            solve_feasible
            and not validation_errors
            and improve_result is not None
            and int(final_score.get("hard_conflict_count", -1)) == 0
        ),
    }


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * min(1.0, max(0.0, float(probability)))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize_runs(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        raise ValueError("At least one report is required")

    def summary(values: list[float]) -> dict[str, float | None]:
        return {
            "minimum": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "p95": _percentile(values, 0.95),
            "maximum": max(values) if values else None,
        }

    stage_names = sorted(
        {
            str(stage)
            for report in reports
            for stage in dict(report.get("stage_seconds") or {})
        }
    )
    return {
        "schema_version": 1,
        "kind": "planora_controlled_end_to_end_performance_series",
        "transport": str(reports[0]["transport"]),
        "configuration": dict(reports[0]["configuration"]),
        "instance": dict(reports[0]["instance"]),
        "repetitions": int(len(reports)),
        "valid_runs": int(sum(bool(report.get("valid")) for report in reports)),
        "all_runs_valid": all(bool(report.get("valid")) for report in reports),
        "timings": {
            "measured_total_seconds": summary(
                [float(report["measured_total_seconds"]) for report in reports]
            ),
            "stages": {
                stage: summary(
                    [
                        float(dict(report.get("stage_seconds") or {})[stage])
                        for report in reports
                        if stage in dict(report.get("stage_seconds") or {})
                    ]
                )
                for stage in stage_names
            },
        },
        "peak_rss_kib_max": max(int(report["peak_rss_kib"]) for report in reports),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": int(os.cpu_count() or 1),
        },
        "runs": reports,
    }


def _single_run(args: argparse.Namespace, transport: str) -> dict[str, Any]:
    kwargs = {
        "mode": str(args.mode),
        "seed": int(args.seed),
        "import_csv": args.import_csv,
        "room_mode": str(args.room_mode),
        "objective_profile": str(args.objective_profile),
        "solve_seconds": float(args.solve_seconds),
        "workers": int(args.workers),
        "improve_iterations": int(args.improve_iterations),
        "improve_seconds": float(args.improve_seconds),
    }
    if transport == "http":
        return run_http_workflow(**kwargs, base_url=args.base_url)
    return run_embedded_workflow(**kwargs)


def _child_command(args: argparse.Namespace, transport: str) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--single-run",
        "--transport",
        str(transport),
        "--mode",
        str(args.mode),
        "--seed",
        str(args.seed),
        "--room-mode",
        str(args.room_mode),
        "--objective-profile",
        str(args.objective_profile),
        "--solve-seconds",
        str(args.solve_seconds),
        "--workers",
        str(args.workers),
        "--improve-iterations",
        str(args.improve_iterations),
        "--improve-seconds",
        str(args.improve_seconds),
    ]
    if args.import_csv:
        command.extend(["--import-csv", str(args.import_csv)])
    if args.base_url:
        command.extend(["--base-url", str(args.base_url)])
    return command


def _fresh_process_run(args: argparse.Namespace, transport: str) -> dict[str, Any]:
    completed = subprocess.run(
        _child_command(args, transport),
        cwd=str(ROOT),
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=max(
            120.0, float(args.solve_seconds) + float(args.improve_seconds) + 90.0
        ),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{transport} benchmark child failed with code {completed.returncode}: "
            f"{completed.stderr[-4000:]}\n{completed.stdout[-4000:]}"
        )
    marker_lines = [
        line for line in completed.stdout.splitlines() if line.startswith(RESULT_MARKER)
    ]
    if not marker_lines:
        raise RuntimeError(
            f"{transport} benchmark child returned no result marker: "
            f"{completed.stdout[-4000:]}"
        )
    return json.loads(marker_lines[-1][len(RESULT_MARKER) :])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure Planora generate/import -> session -> solve -> validation/score "
            "-> response -> improve through embedded and HTTP transports."
        )
    )
    parser.add_argument(
        "--transport", choices=["embedded", "http", "both"], default="both"
    )
    parser.add_argument("--mode", default="target_case")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--import-csv", type=Path)
    parser.add_argument("--room-mode", default="partitioned")
    parser.add_argument("--objective-profile", default="university_fast")
    parser.add_argument("--solve-seconds", type=float, default=15.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--improve-iterations", type=int, default=500)
    parser.add_argument("--improve-seconds", type=float, default=2.0)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--base-url")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeats <= 0 or args.warmup_runs < 0:
        raise ValueError("repeats must be positive and warmup-runs non-negative")
    transports = ["embedded", "http"] if args.transport == "both" else [args.transport]
    if args.single_run:
        if len(transports) != 1:
            raise ValueError("--single-run requires one transport")
        report = _single_run(args, transports[0])
        print(RESULT_MARKER + json.dumps(report, separators=(",", ":")))
        return 0 if bool(report.get("valid")) else 1

    series: dict[str, Any] = {}

    def write_matrix(*, complete: bool) -> None:
        if not args.out:
            return
        payload = {
            "schema_version": 1,
            "kind": "planora_controlled_end_to_end_performance_matrix",
            "complete": bool(complete),
            "requested_transports": transports,
            "results": series,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(args.out.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.out)

    for transport in transports:
        for _ in range(int(args.warmup_runs)):
            _fresh_process_run(args, transport)
        reports = [
            _fresh_process_run(args, transport) for _ in range(int(args.repeats))
        ]
        summary = summarize_runs(reports)
        summary["warmup_runs"] = int(args.warmup_runs)
        summary["fresh_process_per_run"] = True
        series[transport] = summary
        write_matrix(complete=False)

    payload = {
        "schema_version": 1,
        "kind": "planora_controlled_end_to_end_performance_matrix",
        "complete": True,
        "requested_transports": transports,
        "results": series,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        write_matrix(complete=True)
    else:
        print(text)
    return 0 if all(bool(row.get("all_runs_valid")) for row in series.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
