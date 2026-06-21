from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict

from services.contracts import ImproveOptions, SolveOptions
from services.schedule_ops_service import (
    candidate_move_deltas_shared,
    clear_activity_lock_shared,
    cp_sat_polish_shared,
    export_schedule_csv_text,
    improve_schedule_shared,
    move_activity_shared,
    normalize_schedule,
    score_schedule,
    set_activity_lock_shared,
)
from services.solver_service import solve_instance, solve_portfolio
from utils.generator import instance_to_json
from utils.io import instance_from_json


def result_payload(result) -> Dict[str, Any]:
    return {
        "status": int(result.status),
        "raw_status": int(result.raw_status),
        "schedule": result.schedule,
        "hard_conflicts": list(result.hard_conflicts),
        "meta": dict(result.meta or {}),
        "attempts": [
            {
                "room_mode": str(attempt.room_mode),
                "use_objective": bool(attempt.use_objective),
                "time_limit_seconds": attempt.time_limit_seconds,
                "raw_status": int(attempt.raw_status),
                "objective_value": attempt.objective_value,
                "best_objective_bound": attempt.best_objective_bound,
                "relative_gap": attempt.relative_gap,
            }
            for attempt in (result.attempts or [])
        ],
    }


@dataclass
class WorkspaceSession:
    session_id: str
    instance_json: Dict[str, Any]
    schedule: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def instance(self):
        return instance_from_json(self.instance_json)

    def to_dict(self, *, include_workspace: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "session_id": self.session_id,
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
            "activities": int(len((self.instance_json.get("activities") or {}))),
            "schedule_activities": int(len(self.schedule)),
            "meta": dict(self.meta or {}),
        }
        if include_workspace:
            payload["instance"] = self.instance_json
            payload["schedule"] = normalize_schedule(self.schedule)
        return payload


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, WorkspaceSession] = {}

    def create(
        self,
        *,
        instance_json: Dict[str, Any],
        schedule: Dict[Any, Dict[str, Any]] | None = None,
        meta: Dict[str, Any] | None = None,
    ) -> WorkspaceSession:
        session = WorkspaceSession(
            session_id=uuid.uuid4().hex,
            instance_json=dict(instance_json),
            schedule=normalize_schedule(schedule),
            meta=dict(meta or {}),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> WorkspaceSession:
        with self._lock:
            session = self._sessions.get(str(session_id))
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        return session

    def restore(
        self,
        *,
        session_id: str,
        instance_json: Dict[str, Any],
        schedule: Dict[Any, Dict[str, Any]],
        meta: Dict[str, Any],
        created_at: float,
        updated_at: float,
    ) -> WorkspaceSession:
        session = WorkspaceSession(
            session_id=str(session_id),
            instance_json=dict(instance_json),
            schedule=normalize_schedule(schedule),
            meta=dict(meta),
            created_at=float(created_at),
            updated_at=float(updated_at),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def update(
        self,
        session_id: str,
        *,
        instance_json: Dict[str, Any] | None = None,
        schedule: Dict[Any, Dict[str, Any]] | None = None,
        meta: Dict[str, Any] | None = None,
    ) -> WorkspaceSession:
        session = self.get(session_id)
        with self._lock:
            if instance_json is not None:
                session.instance_json = dict(instance_json)
            if schedule is not None:
                session.schedule = normalize_schedule(schedule)
            if meta is not None:
                session.meta = dict(meta)
            session.updated_at = time.time()
        return session


@dataclass
class JobRecord:
    job_id: str
    action: str
    tenant_id: str = "default"
    created_by: str = "unknown"
    status: str = "queued"
    progress: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action,
            "tenant_id": self.tenant_id,
            "created_by": self.created_by,
            "status": self.status,
            "progress": dict(self.progress or {}),
            "result": self.result,
            "error": self.error,
            "cancel_requested": bool(self.cancel_requested),
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
        }


class JobStore:
    def __init__(self, on_change: Callable[[JobRecord], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}
        self._on_change = on_change

    def submit(
        self,
        action: str,
        fn: Callable[[JobRecord], Dict[str, Any]],
        *,
        tenant_id: str = "default",
        created_by: str = "unknown",
    ) -> JobRecord:
        job = JobRecord(
            job_id=uuid.uuid4().hex,
            action=str(action),
            tenant_id=str(tenant_id),
            created_by=str(created_by),
        )
        with self._lock:
            self._jobs[job.job_id] = job

        def _run() -> None:
            self.update(job.job_id, status="running", progress={"event": "started"})
            try:
                result = fn(job)
                if job.cancel_requested:
                    self.update(job.job_id, status="cancelled", result=result)
                else:
                    self.update(job.job_id, status="complete", result=result, progress={"event": "complete"})
            except Exception as exc:
                self.update(job.job_id, status="failed", error=str(exc), progress={"event": "failed"})

        # Let the submit request return its job handle before CPU-heavy Python
        # work starts competing for the interpreter and SQLite writer lock.
        timer = threading.Timer(0.05, _run)
        timer.daemon = True
        timer.start()
        return job

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._jobs.get(str(job_id))
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        return job

    def update(self, job_id: str, **updates: Any) -> JobRecord:
        with self._lock:
            job = self._jobs[str(job_id)]
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = time.time()
        if self._on_change:
            self._on_change(job)
        return job

    def cancel(self, job_id: str) -> JobRecord:
        return self.update(job_id, cancel_requested=True)

    def restore(self, payload: Dict[str, Any]) -> JobRecord:
        job = JobRecord(
            job_id=str(payload["job_id"]),
            action=str(payload["action"]),
            tenant_id=str(payload["tenant_id"]),
            created_by=str(payload["created_by"]),
            status=str(payload["status"]),
            progress=dict(payload.get("progress") or {}),
            result=(dict(payload["result"]) if isinstance(payload.get("result"), dict) else None),
            error=(str(payload["error"]) if payload.get("error") else None),
            cancel_requested=bool(payload.get("cancel_requested")),
            created_at=float(payload["created_at"]),
            updated_at=float(payload["updated_at"]),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job


def run_workspace_action(
    *,
    instance_json: Dict[str, Any],
    schedule: Dict[Any, Dict[str, Any]] | None,
    action: str,
    payload: Dict[str, Any] | None = None,
    progress_hook=None,
) -> Dict[str, Any]:
    payload = dict(payload or {})
    inst = instance_from_json(instance_json)
    schedule_i = normalize_schedule(schedule)
    action = str(action)

    if action == "solve":
        result = solve_instance(inst, SolveOptions(**dict(payload.get("options") or {})))
        return result_payload(result)
    if action == "portfolio":
        portfolio = solve_portfolio(inst, SolveOptions(**dict(payload.get("options") or {})))
        return {
            "best_index": int(portfolio.best_index),
            "candidates": [
                {
                    "name": str(candidate.name),
                    "options": dict(candidate.options.__dict__),
                    "result": result_payload(candidate.result),
                    "soft_penalty": candidate.soft_penalty,
                    "rank_explanation": str(candidate.rank_explanation),
                }
                for candidate in portfolio.candidates
            ],
        }
    if action in {"score", "conflicts"}:
        return score_schedule(inst, schedule_i)
    if action == "improve":
        return improve_schedule_shared(
            inst,
            schedule_i,
            ImproveOptions(**dict(payload.get("options") or {})),
            focus_term=str(payload.get("focus_term", "") or ""),
            progress_hook=progress_hook,
        )
    if action == "cp_polish":
        return cp_sat_polish_shared(
            inst,
            schedule_i,
            SolveOptions(**dict(payload.get("options") or {})),
            focus_term=str(payload.get("focus_term", "") or ""),
            affected_limit=int(payload.get("affected_limit", 100) or 100),
        )
    if action == "move_activity":
        return move_activity_shared(
            inst,
            schedule_i,
            activity_id=int(payload["activity_id"]),
            week=payload.get("week"),
            day=payload.get("day"),
            slot=payload.get("slot"),
            room_id=payload.get("room_id"),
            staff_id=payload.get("staff_id"),
            enforce_hard_conflict_free=bool(payload.get("enforce_hard_conflict_free", True)),
        )
    if action == "move_deltas":
        return candidate_move_deltas_shared(
            inst,
            schedule_i,
            activity_id=int(payload["activity_id"]),
            week=(int(payload["week"]) if payload.get("week") not in (None, "") else None),
            room_id=(int(payload["room_id"]) if payload.get("room_id") not in (None, "") else None),
            staff_id=(int(payload["staff_id"]) if payload.get("staff_id") not in (None, "") else None),
            limit=(int(payload["limit"]) if payload.get("limit") not in (None, "") else None),
        )
    if action == "lock_activity":
        return set_activity_lock_shared(
            inst,
            schedule_i,
            activity_id=int(payload["activity_id"]),
            fields=list(payload.get("fields") or ["day", "slot", "room_id"]),
        )
    if action == "unlock_activity":
        activity_id = payload.get("activity_id")
        return clear_activity_lock_shared(
            inst,
            schedule_i,
            activity_id=(int(activity_id) if activity_id not in (None, "") else None),
        )
    if action == "export_csv":
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", newline="", delete=False) as fh:
            tmp_path = Path(fh.name)
        try:
            content = export_schedule_csv_text(inst, schedule_i, tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return {
            "filename": str(payload.get("filename", "planora-schedule.csv") or "planora-schedule.csv"),
            "content_type": "text/csv",
            "content": content,
        }
    raise ValueError(f"Unsupported action: {action}")


def safe_project_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned[:80] or "project"


def save_web_project(root: str | Path, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    project_dir = Path(root).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    project_name = safe_project_name(name)
    path = (project_dir / f"{project_name}.json").resolve()
    if project_dir not in path.parents:
        raise ValueError("Invalid project path.")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": project_name, "path": str(path)}


def list_web_projects(root: str | Path) -> Dict[str, Any]:
    project_dir = Path(root).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    projects = []
    for path in sorted(project_dir.glob("*.json")):
        projects.append({"name": path.stem, "path": str(path), "updated_at": path.stat().st_mtime})
    return {"projects": projects}


def load_web_project(root: str | Path, name: str) -> Dict[str, Any]:
    project_dir = Path(root).resolve()
    path = (project_dir / f"{safe_project_name(name)}.json").resolve()
    if project_dir not in path.parents or not path.exists():
        raise FileNotFoundError(f"Unknown project: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Project payload must be an object.")
    return payload
