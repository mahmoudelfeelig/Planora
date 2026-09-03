from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from utils.domain import Instance


ROOM_CERTIFICATE_SCHEMA = "planora.room-certificate.v1"
HALL_CERTIFICATE_RULE = "fixed-time-hall-deficiency.v1"
CONTEXTUAL_CUT_SCHEMA = "planora.contextual-hall-cut.v1"
CONTEXTUAL_CUT_RULE = "option-expanded-hall-gamma.v1"
EFFECTIVE_DOMAIN_RULE = "candidate-rooms-for-members.v1"


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_canonical(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported proof value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the one canonical representation used by every lineage ID."""
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _content_id(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"


def certificate_id_for_payload(payload: Mapping[str, Any]) -> str:
    body = {str(key): value for key, value in payload.items() if key != "certificate_id"}
    return _content_id("room-cert-v1", body)


def cut_id_for_inequality(
    terms: Sequence[Mapping[str, Any]],
    rhs: int,
) -> str:
    normalized_terms = sorted(
        (
            {
                "representative_activity_id": int(term["representative_activity_id"]),
                "start": int(term["start"]),
            }
            for term in terms
        ),
        key=lambda item: (item["representative_activity_id"], item["start"]),
    )
    return _content_id(
        "room-cut-v1",
        {
            "terms": normalized_terms,
            "sense": "<=",
            "rhs": int(rhs),
        },
    )


def derivation_id_for_payload(payload: Mapping[str, Any]) -> str:
    body = {str(key): value for key, value in payload.items() if key != "derivation_id"}
    return _content_id("room-derivation-v1", body)


def room_context_id(inst: Instance) -> str:
    """Fingerprint every instance field consumed by effective room domains."""
    payload = {
        "rooms": [
            {
                "id": int(room_id),
                "capacity": int(room.capacity),
                "room_type": str(room.room_type),
                "campus": str(getattr(room, "campus", "") or ""),
                "building": str(getattr(room, "building", "") or ""),
                "floor": str(getattr(room, "floor", "") or ""),
                "specialization_tags": sorted(
                    str(value)
                    for value in (
                        getattr(room, "specialization_tags", set()) or set()
                    )
                ),
                "availability": (
                    None
                    if getattr(room, "availability", None) is None
                    else sorted(
                        [str(day), int(slot)]
                        for day, slot in room.availability
                    )
                ),
            }
            for room_id, room in sorted(inst.rooms.items())
        ],
        "activities": [
            {
                "id": int(activity_id),
                "kind": str(activity.kind),
                "duration": int(activity.duration),
                "group_ids": sorted(int(value) for value in activity.group_ids),
                "requires_specialization": getattr(
                    activity,
                    "requires_specialization",
                    None,
                ),
            }
            for activity_id, activity in sorted(inst.activities.items())
        ],
        "groups": [
            {
                "id": int(group_id),
                "size": int(group.size),
                "demand_scenarios": dict(
                    sorted(
                        (
                            str(name),
                            int(value),
                        )
                        for name, value in (
                            getattr(group, "demand_scenarios", {}) or {}
                        ).items()
                    )
                ),
                "demand_deviation": int(
                    getattr(group, "demand_deviation", 0) or 0
                ),
            }
            for group_id, group in sorted(inst.groups.items())
        ],
        "hard_constraints": dict(
            sorted(
                (str(key), value)
                for key, value in (
                    getattr(inst, "hard_constraints", {}) or {}
                ).items()
                if str(key)
                in {
                    "enforce_room_capacity",
                    "enforce_room_availability",
                    "enforce_building_closures",
                }
            )
        ),
        "locked_room_ids": {
            str(activity_id): int(lock["room_id"])
            for activity_id, lock in sorted(
                (getattr(inst, "locked_activities", {}) or {}).items()
            )
            if isinstance(lock, Mapping) and lock.get("room_id") is not None
        },
        "room_closures": list(getattr(inst, "room_closures", []) or []),
        "demand_policy": dict(getattr(inst, "demand_policy", {}) or {}),
    }
    return _content_id("room-context-v1", payload)


@dataclass(frozen=True)
class ProofCheckResult:
    valid: bool
    errors: tuple[str, ...] = ()
    reconstructed: Mapping[str, Any] = field(default_factory=dict)


def _int_tuple(value: Any, *, field_name: str, errors: list[str]) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        errors.append(f"missing_or_invalid:{field_name}")
        return ()
    try:
        normalized = tuple(int(item) for item in value)
    except (TypeError, ValueError):
        errors.append(f"non_integer:{field_name}")
        return ()
    if normalized != tuple(sorted(set(normalized))):
        errors.append(f"not_sorted_unique:{field_name}")
    return normalized


def _integer(value: Any, *, field_name: str, errors: list[str]) -> int | None:
    if isinstance(value, bool):
        errors.append(f"missing_or_invalid:{field_name}")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"missing_or_invalid:{field_name}")
        return None


def check_hall_certificate(
    inst: Instance,
    certificate: Mapping[str, Any],
) -> ProofCheckResult:
    """Independently replay a serialized fixed-time Hall witness."""
    errors: list[str] = []
    if not isinstance(certificate, Mapping):
        return ProofCheckResult(False, ("certificate_not_mapping",))

    expected_id: str | None = None
    try:
        expected_id = certificate_id_for_payload(certificate)
    except (TypeError, ValueError) as exc:
        errors.append(f"certificate_not_canonical:{type(exc).__name__}")
    if not certificate.get("certificate_id"):
        errors.append("missing:certificate_id")
    elif expected_id is not None and str(certificate["certificate_id"]) != expected_id:
        errors.append("certificate_id_mismatch")
    if certificate.get("schema_version") != ROOM_CERTIFICATE_SCHEMA:
        errors.append("unsupported:certificate_schema")
    if certificate.get("certificate_type") != "hall_deficiency":
        errors.append("unsupported:certificate_type")

    activity_ids = _int_tuple(
        certificate.get("activity_ids"),
        field_name="activity_ids",
        errors=errors,
    )
    representative_ids = _int_tuple(
        certificate.get("representative_activity_ids"),
        field_name="representative_activity_ids",
        errors=errors,
    )
    witness_rooms = _int_tuple(
        certificate.get("candidate_room_ids"),
        field_name="candidate_room_ids",
        errors=errors,
    )
    if any(room_id not in inst.rooms for room_id in witness_rooms):
        errors.append("unknown:witness_room")

    proof = certificate.get("proof")
    if not isinstance(proof, Mapping):
        errors.append("missing_or_invalid:proof")
        proof = {}
    if proof.get("proof_rule") != HALL_CERTIFICATE_RULE:
        errors.append("unsupported:hall_proof_rule")
    if proof.get("room_context_id") != room_context_id(inst):
        errors.append("room_context_id_mismatch")

    witness_slot = proof.get("witness_slot")
    if not isinstance(witness_slot, Mapping):
        errors.append("missing_or_invalid:witness_slot")
        witness_slot = {}
    week = _integer(witness_slot.get("week"), field_name="witness_slot.week", errors=errors)
    slot = _integer(witness_slot.get("slot"), field_name="witness_slot.slot", errors=errors)
    day = witness_slot.get("day")
    if not isinstance(day, str) or not day:
        errors.append("missing_or_invalid:witness_slot.day")
        day = ""
    if certificate.get("week") != week:
        errors.append("mismatch:certificate_week")
    if certificate.get("day") != day:
        errors.append("mismatch:certificate_day")
    if certificate.get("slot") != slot:
        errors.append("mismatch:certificate_slot")

    proof_rooms = _int_tuple(
        proof.get("witness_room_ids"),
        field_name="proof.witness_room_ids",
        errors=errors,
    )
    if proof_rooms != witness_rooms:
        errors.append("mismatch:witness_room_ids")

    raw_jobs = proof.get("representative_jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        errors.append("missing_or_invalid:representative_jobs")
        raw_jobs = []

    reconstructed_jobs: list[dict[str, Any]] = []
    seen_representatives: set[int] = set()
    all_members: set[int] = set()
    effective_union: set[int] = set()
    for index, raw_job in enumerate(raw_jobs):
        prefix = f"representative_jobs[{index}]"
        if not isinstance(raw_job, Mapping):
            errors.append(f"missing_or_invalid:{prefix}")
            continue
        representative = _integer(
            raw_job.get("representative_activity_id"),
            field_name=f"{prefix}.representative_activity_id",
            errors=errors,
        )
        members = _int_tuple(
            raw_job.get("member_activity_ids"),
            field_name=f"{prefix}.member_activity_ids",
            errors=errors,
        )
        effective_rooms = _int_tuple(
            raw_job.get("effective_room_ids"),
            field_name=f"{prefix}.effective_room_ids",
            errors=errors,
        )
        assumptions = raw_job.get("domain_assumptions")
        if not isinstance(assumptions, Mapping):
            errors.append(f"missing_or_invalid:{prefix}.domain_assumptions")
            assumptions = {}

        if representative is None:
            continue
        if representative in seen_representatives:
            errors.append("duplicate:representative_activity_id")
        seen_representatives.add(representative)
        if representative not in members:
            errors.append(f"representative_not_member:{representative}")
        if any(member not in inst.activities for member in members):
            errors.append(f"unknown:member_activity:{representative}")
            continue

        expected_duration = max(
            (int(inst.activities[member].duration) for member in members),
            default=0,
        )
        expected_assumptions = {
            "domain_rule": EFFECTIVE_DOMAIN_RULE,
            "member_activity_ids": list(members),
            "week": week,
            "day": day,
            "start_slot": raw_job.get("start_slot"),
            "duration": expected_duration,
        }
        if _canonical(assumptions) != _canonical(expected_assumptions):
            errors.append(f"mismatch:{prefix}.domain_assumptions")

        start_slot = _integer(
            raw_job.get("start_slot"),
            field_name=f"{prefix}.start_slot",
            errors=errors,
        )
        duration = _integer(
            raw_job.get("duration"),
            field_name=f"{prefix}.duration",
            errors=errors,
        )
        if duration != expected_duration:
            errors.append(f"mismatch:{prefix}.duration")
        if week is not None and any(
            int(inst.activities[member].week) != week for member in members
        ):
            errors.append(f"mismatch:{prefix}.week")
        if (
            start_slot is not None
            and slot is not None
            and duration is not None
            and not start_slot <= slot < start_slot + duration
        ):
            errors.append(f"not_covering_witness:{representative}")

        if week is not None and start_slot is not None and duration is not None and day:
            try:
                from core.room_decomposition import candidate_rooms_for_members

                replayed = tuple(
                    candidate_rooms_for_members(
                        inst,
                        members,
                        week=week,
                        day=day,
                        start_slot=start_slot,
                        duration=duration,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(f"domain_replay_error:{representative}:{type(exc).__name__}")
                replayed = ()
            if replayed != effective_rooms:
                errors.append(f"mismatch:{prefix}.effective_room_ids")

        if not set(effective_rooms).issubset(witness_rooms):
            errors.append(f"domain_not_subset_of_witness:{representative}")
        all_members.update(members)
        effective_union.update(effective_rooms)
        reconstructed_jobs.append(
            {
                "representative_activity_id": representative,
                "member_activity_ids": list(members),
                "effective_room_ids": list(effective_rooms),
                "start_slot": start_slot,
                "duration": duration,
            }
        )

    if tuple(sorted(seen_representatives)) != representative_ids:
        errors.append("mismatch:representative_activity_ids")
    if tuple(sorted(all_members)) != activity_ids:
        errors.append("mismatch:activity_ids")
    if len(reconstructed_jobs) <= len(witness_rooms):
        errors.append("hall_witness_not_deficient")
    deficiency = len(reconstructed_jobs) - len(witness_rooms)
    if certificate.get("deficiency") != deficiency:
        errors.append("mismatch:deficiency")
    if proof.get("job_count") != len(reconstructed_jobs):
        errors.append("mismatch:proof.job_count")
    if proof.get("witness_room_count") != len(witness_rooms):
        errors.append("mismatch:proof.witness_room_count")
    if proof.get("deficiency") != deficiency:
        errors.append("mismatch:proof.deficiency")

    return ProofCheckResult(
        valid=not errors,
        errors=tuple(errors),
        reconstructed={
            "certificate_id": expected_id,
            "representative_jobs": reconstructed_jobs,
            "effective_room_union": sorted(effective_union),
            "witness_room_ids": list(witness_rooms),
            "deficiency": int(deficiency),
        },
    )


def _check_contextual_hall_derivation(
    inst: Instance,
    certificate: Mapping[str, Any],
    derivation: Mapping[str, Any],
) -> ProofCheckResult:
    """Replay the complete option-expanded cut evidence without a CP model."""
    errors: list[str] = []
    certificate_check = check_hall_certificate(inst, certificate)
    errors.extend(f"certificate:{error}" for error in certificate_check.errors)
    if not isinstance(derivation, Mapping):
        return ProofCheckResult(False, tuple(errors + ["derivation_not_mapping"]))

    if derivation.get("schema_version") != CONTEXTUAL_CUT_SCHEMA:
        errors.append("unsupported:derivation_schema")
    if derivation.get("cut_kind") != "contextual_hall":
        errors.append("unsupported:cut_kind")
    if derivation.get("proof_rule") != CONTEXTUAL_CUT_RULE:
        errors.append("unsupported:cut_proof_rule")
    if derivation.get("certificate_id") != certificate.get("certificate_id"):
        errors.append("mismatch:certificate_id_link")
    if derivation.get("room_context_id") != room_context_id(inst):
        errors.append("room_context_id_mismatch")

    expected_derivation_id: str | None = None
    try:
        expected_derivation_id = derivation_id_for_payload(derivation)
    except (TypeError, ValueError) as exc:
        errors.append(f"derivation_not_canonical:{type(exc).__name__}")
    if not derivation.get("derivation_id"):
        errors.append("missing:derivation_id")
    elif (
        expected_derivation_id is not None
        and derivation.get("derivation_id") != expected_derivation_id
    ):
        errors.append("derivation_id_mismatch")

    proof = certificate.get("proof")
    if not isinstance(proof, Mapping):
        proof = {}
    certificate_jobs = proof.get("representative_jobs")
    if not isinstance(certificate_jobs, list):
        certificate_jobs = []
    jobs_by_representative = {
        int(job["representative_activity_id"]): job
        for job in certificate_jobs
        if isinstance(job, Mapping) and job.get("representative_activity_id") is not None
    }
    representatives = tuple(sorted(jobs_by_representative))

    witness_rooms = _int_tuple(
        derivation.get("witness_room_ids"),
        field_name="derivation.witness_room_ids",
        errors=errors,
    )
    certificate_rooms = tuple(int(value) for value in certificate.get("candidate_room_ids", ()))
    if witness_rooms != certificate_rooms:
        errors.append("mismatch:derivation_witness_rooms")

    week = certificate.get("week")
    day = certificate.get("day")
    witness_slot = certificate.get("slot")
    if derivation.get("week") != week:
        errors.append("mismatch:derivation_week")
    if derivation.get("day") != day:
        errors.append("mismatch:derivation_day")
    if derivation.get("slot") != witness_slot:
        errors.append("mismatch:derivation_slot")

    raw_start_domains = derivation.get("master_start_domains")
    if not isinstance(raw_start_domains, Mapping):
        errors.append("missing_or_invalid:master_start_domains")
        raw_start_domains = {}
    start_domains: dict[int, tuple[int, ...]] = {}
    expected_members = sorted(
        {
            int(member)
            for job in certificate_jobs
            if isinstance(job, Mapping)
            for member in (job.get("member_activity_ids") or [])
        }
    )
    try:
        supplied_domain_keys = sorted(int(key) for key in raw_start_domains)
    except (TypeError, ValueError):
        supplied_domain_keys = []
        errors.append("non_integer:master_start_domains.key")
    if supplied_domain_keys != expected_members:
        errors.append("mismatch:master_start_domain_members")
    for member in expected_members:
        raw_domain = raw_start_domains.get(str(member), raw_start_domains.get(member))
        domain = _int_tuple(
            raw_domain,
            field_name=f"master_start_domains.{member}",
            errors=errors,
        )
        if any(start < 0 or start >= len(inst.days) * int(inst.slots_per_day) for start in domain):
            errors.append(f"out_of_range:master_start_domains.{member}")
        start_domains[member] = domain

    expected_records: dict[tuple[int, int], dict[str, Any]] = {}
    for representative in representatives:
        job = jobs_by_representative[representative]
        members = tuple(int(value) for value in job.get("member_activity_ids") or [])
        duration = int(job.get("duration"))
        for start in start_domains.get(representative, ()):
            day_index, start_slot = divmod(int(start), int(inst.slots_per_day))
            if day_index >= len(inst.days):
                continue
            if (
                inst.days[day_index] != day
                or witness_slot is None
                or not start_slot <= int(witness_slot) < start_slot + duration
            ):
                continue
            if any(int(start) not in start_domains.get(member, ()) for member in members):
                continue
            assumptions = {
                "domain_rule": EFFECTIVE_DOMAIN_RULE,
                "member_activity_ids": list(members),
                "week": int(week),
                "day": str(day),
                "start_slot": int(start_slot),
                "duration": int(duration),
            }
            try:
                from core.room_decomposition import candidate_rooms_for_members

                effective_rooms = tuple(
                    candidate_rooms_for_members(
                        inst,
                        members,
                        week=int(week),
                        day=str(day),
                        start_slot=int(start_slot),
                        duration=int(duration),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive boundary
                errors.append(
                    f"domain_replay_error:{representative}:{start}:{type(exc).__name__}"
                )
                continue
            if set(effective_rooms).issubset(witness_rooms):
                expected_records[(representative, int(start))] = {
                    "representative_activity_id": int(representative),
                    "member_activity_ids": list(members),
                    "start": int(start),
                    "effective_room_ids": list(effective_rooms),
                    "domain_assumptions": assumptions,
                }

    raw_records = derivation.get("counted_starts")
    if not isinstance(raw_records, list):
        errors.append("missing_or_invalid:counted_starts")
        raw_records = []
    supplied_records: dict[tuple[int, int], Mapping[str, Any]] = {}
    for index, record in enumerate(raw_records):
        if not isinstance(record, Mapping):
            errors.append(f"missing_or_invalid:counted_starts[{index}]")
            continue
        representative = _integer(
            record.get("representative_activity_id"),
            field_name=f"counted_starts[{index}].representative_activity_id",
            errors=errors,
        )
        start = _integer(
            record.get("start"),
            field_name=f"counted_starts[{index}].start",
            errors=errors,
        )
        if representative is None or start is None:
            continue
        key = (representative, start)
        if key in supplied_records:
            errors.append("duplicate:counted_start")
        supplied_records[key] = record

    if set(supplied_records) != set(expected_records):
        missing = sorted(set(expected_records) - set(supplied_records))
        unexpected = sorted(set(supplied_records) - set(expected_records))
        if missing:
            errors.append(f"incomplete:counted_starts:{missing}")
        if unexpected:
            errors.append(f"unexpected:counted_starts:{unexpected}")
    for key in sorted(set(supplied_records) & set(expected_records)):
        if _canonical(supplied_records[key]) != _canonical(expected_records[key]):
            errors.append(f"mismatch:counted_start:{key}")

    gamma_rooms = sorted(
        {
            int(room_id)
            for record in expected_records.values()
            for room_id in record["effective_room_ids"]
        }
    )
    supplied_gamma = _int_tuple(
        derivation.get("derived_gamma_room_ids"),
        field_name="derived_gamma_room_ids",
        errors=errors,
    )
    if supplied_gamma != tuple(gamma_rooms):
        errors.append("mismatch:derived_gamma_room_ids")
    if not set(gamma_rooms).issubset(witness_rooms):
        errors.append("derived_gamma_not_subset_of_witness")
    if derivation.get("rhs") != len(gamma_rooms):
        errors.append("mismatch:rhs")
    if derivation.get("term_count") != len(expected_records):
        errors.append("mismatch:term_count")

    incumbent_starts = {
        str(representative): (
            int(inst.days.index(str(day))) * int(inst.slots_per_day)
            + int(jobs_by_representative[representative]["start_slot"])
        )
        for representative in representatives
        if day in inst.days
    }
    if _canonical(derivation.get("incumbent_starts")) != _canonical(incumbent_starts):
        errors.append("mismatch:incumbent_starts")
    if any(
        (representative, incumbent_starts.get(str(representative), -1))
        not in expected_records
        for representative in representatives
    ):
        errors.append("incumbent_term_missing")
    if len(representatives) <= len(gamma_rooms):
        errors.append("cut_does_not_exclude_incumbent")
    if derivation.get("incumbent_term_count") != len(representatives):
        errors.append("mismatch:incumbent_term_count")

    expected_strengthened = bool(
        len(expected_records) > len(representatives)
        or len(gamma_rooms) < max(0, len(representatives) - 1)
    )
    if derivation.get("strengthened") is not expected_strengthened:
        errors.append("mismatch:strengthened")

    inequality_terms = [
        {
            "representative_activity_id": representative,
            "start": start,
        }
        for representative, start in sorted(expected_records)
    ]
    expected_cut_id = cut_id_for_inequality(inequality_terms, len(gamma_rooms))
    if not derivation.get("cut_id"):
        errors.append("missing:cut_id")
    elif derivation.get("cut_id") != expected_cut_id:
        errors.append("cut_id_mismatch")

    return ProofCheckResult(
        valid=not errors,
        errors=tuple(errors),
        reconstructed={
            "certificate_id": certificate.get("certificate_id"),
            "derivation_id": expected_derivation_id,
            "cut_id": expected_cut_id,
            "counted_starts": [expected_records[key] for key in sorted(expected_records)],
            "derived_gamma_room_ids": gamma_rooms,
            "rhs": len(gamma_rooms),
            "incumbent_term_count": len(representatives),
        },
    )


def check_contextual_hall_derivation(
    inst: Instance,
    certificate: Mapping[str, Any],
    derivation: Mapping[str, Any],
) -> ProofCheckResult:
    """Reject malformed evidence instead of leaking parser exceptions."""
    try:
        return _check_contextual_hall_derivation(inst, certificate, derivation)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        return ProofCheckResult(
            False,
            (f"malformed_derivation:{type(exc).__name__}",),
        )
