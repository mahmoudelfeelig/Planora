from __future__ import annotations

from copy import deepcopy

from core.adaptive_lns import (
    CertificateGuidedAdaptiveLNS,
    RepairOutcome,
    certificate_signals_from_decomposition,
)
from core.room_decomposition import ExactRoomSubproblem, RoomConflictCertificate
from core.room_proof_checker import (
    EFFECTIVE_DOMAIN_RULE,
    HALL_CERTIFICATE_RULE,
    check_contextual_hall_derivation,
    check_hall_certificate,
    cut_id_for_inequality,
    derivation_id_for_payload,
    room_context_id,
)
from core.solver_cp_sat import TimetableSolver
from utils.domain import (
    Activity,
    Course,
    Group,
    Instance,
    Program,
    Room,
    StaffMember,
)


def _instance(
    *,
    activity_count: int = 2,
    include_small_room: bool = True,
    duration: int = 1,
    slots_per_day: int = 1,
) -> Instance:
    rooms = {1: Room(id=1, name="R1", capacity=50, room_type="LECTURE")}
    if include_small_room:
        rooms[2] = Room(id=2, name="R2-small", capacity=10, room_type="LECTURE")
    activity_ids = range(1, activity_count + 1)
    return Instance(
        days=["MON"],
        slots_per_day=slots_per_day,
        weeks=[1],
        programs={
            1: Program(
                id=1,
                name="P",
                course_ids=list(activity_ids),
                group_ids=list(activity_ids),
            )
        },
        groups={
            activity_id: Group(
                id=activity_id,
                name=f"G{activity_id}",
                program_id=1,
                size=40,
                course_ids=[activity_id],
            )
            for activity_id in activity_ids
        },
        courses={
            activity_id: Course(
                id=activity_id,
                code=f"C{activity_id}",
                name=f"C{activity_id}",
                structure_type="LEC_ONLY",
                lecture_count=duration,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                prof_id=activity_id,
                ta_id=activity_id + activity_count,
            )
            for activity_id in activity_ids
        },
        staff={
            staff_id: StaffMember(
                id=staff_id,
                name=f"S{staff_id}",
                is_prof=staff_id <= activity_count,
                available_days={"MON"},
                max_slots_per_day=None,
                max_slots_per_week=None,
                can_teach_courses={
                    staff_id
                    if staff_id <= activity_count
                    else staff_id - activity_count
                },
            )
            for staff_id in range(1, activity_count * 2 + 1)
        },
        rooms=rooms,
        activities={
            activity_id: Activity(
                id=activity_id,
                course_id=activity_id,
                week=1,
                kind="LEC",
                duration=duration,
                group_ids=[activity_id],
                prof_id=activity_id,
                ta_id=activity_id + activity_count,
            )
            for activity_id in activity_ids
        },
    )


def _schedule(
    activity_count: int = 2,
    *,
    duration: int = 1,
) -> dict[int, dict[str, object]]:
    return {
        activity_id: {
            "room_id": None,
            "staff_id": activity_id,
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": duration,
            "group_ids": [activity_id],
            "course_id": activity_id,
            "kind": "LEC",
        }
        for activity_id in range(1, activity_count + 1)
    }


def _generated_lineage() -> tuple[Instance, dict[str, object], dict[str, object]]:
    inst = _instance(
        include_small_room=False,
        duration=2,
        slots_per_day=3,
    )
    schedule = _schedule(duration=2)
    certificate = next(
        item
        for item in ExactRoomSubproblem(
            inst,
            schedule,
            optimize=False,
        )._hall_certificates()
        if item.slot == 1
    )
    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    assert model._add_room_certificate_cut(certificate, schedule)
    return inst, certificate.to_dict(), dict(model._last_room_cut_metadata)


def test_certificate_and_cut_ids_are_content_deterministic() -> None:
    inst_a, certificate_a, derivation_a = _generated_lineage()
    inst_b, certificate_b, derivation_b = _generated_lineage()

    assert room_context_id(inst_a) == room_context_id(inst_b)
    assert certificate_a["certificate_id"] == certificate_b["certificate_id"]
    assert derivation_a["cut_id"] == derivation_b["cut_id"]
    assert derivation_a["derivation_id"] == derivation_b["derivation_id"]
    assert derivation_a["certificate_id"] == certificate_a["certificate_id"]
    assert check_hall_certificate(inst_a, certificate_a).valid
    assert check_contextual_hall_derivation(
        inst_a,
        certificate_a,
        derivation_a,
    ).valid


def test_checker_rejects_tampered_or_incomplete_certificate_evidence() -> None:
    inst, certificate, _derivation = _generated_lineage()

    tampered = deepcopy(certificate)
    tampered["proof"]["representative_jobs"][0]["effective_room_ids"] = []
    result = check_hall_certificate(inst, tampered)
    assert not result.valid
    assert "certificate_id_mismatch" in result.errors
    assert any("effective_room_ids" in error for error in result.errors)

    incomplete = deepcopy(certificate)
    incomplete["proof"]["representative_jobs"][0].pop("domain_assumptions")
    result = check_hall_certificate(inst, incomplete)
    assert not result.valid
    assert any("domain_assumptions" in error for error in result.errors)


def test_checker_reconstructs_and_rejects_rehashed_incomplete_cut_terms() -> None:
    inst, certificate, derivation = _generated_lineage()
    incomplete = deepcopy(derivation)
    incomplete["counted_starts"] = incomplete["counted_starts"][:-1]
    incomplete["term_count"] = len(incomplete["counted_starts"])
    incomplete["cut_id"] = cut_id_for_inequality(
        incomplete["counted_starts"],
        int(incomplete["rhs"]),
    )
    incomplete["derivation_id"] = derivation_id_for_payload(incomplete)

    result = check_contextual_hall_derivation(inst, certificate, incomplete)
    assert not result.valid
    assert any(error.startswith("incomplete:counted_starts") for error in result.errors)

    altered = deepcopy(derivation)
    altered["counted_starts"][0]["effective_room_ids"] = []
    altered["derivation_id"] = derivation_id_for_payload(altered)
    result = check_contextual_hall_derivation(inst, certificate, altered)
    assert not result.valid
    assert any(error.startswith("mismatch:counted_start") for error in result.errors)


def test_gamma_rhs_strictly_dominates_a_nonminimal_witness_room_rhs() -> None:
    inst = _instance(activity_count=3, include_small_room=True)
    schedule = _schedule(3)
    jobs = [
        {
            "representative_activity_id": activity_id,
            "member_activity_ids": [activity_id],
            "start_slot": 0,
            "duration": 1,
            "effective_room_ids": [1],
            "domain_assumptions": {
                "domain_rule": EFFECTIVE_DOMAIN_RULE,
                "member_activity_ids": [activity_id],
                "week": 1,
                "day": "MON",
                "start_slot": 0,
                "duration": 1,
            },
        }
        for activity_id in (1, 2, 3)
    ]
    certificate = RoomConflictCertificate(
        certificate_type="hall_deficiency",
        activity_ids=(1, 2, 3),
        representative_activity_ids=(1, 2, 3),
        candidate_room_ids=(1, 2),
        week=1,
        day="MON",
        slot=0,
        deficiency=1,
        message="Three fixed jobs have domains contained in a two-room witness.",
        proof={
            "proof_rule": HALL_CERTIFICATE_RULE,
            "room_context_id": room_context_id(inst),
            "witness_slot": {"week": 1, "day": "MON", "slot": 0},
            "representative_jobs": jobs,
            "witness_room_ids": [1, 2],
            "job_count": 3,
            "witness_room_count": 2,
            "deficiency": 1,
        },
    )
    assert check_hall_certificate(inst, certificate.to_dict()).valid

    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    assert model._add_room_certificate_cut(certificate, schedule)
    derivation = model._last_room_cut_metadata

    assert derivation["cut_kind"] == "contextual_hall"
    assert derivation["witness_room_ids"] == [1, 2]
    assert derivation["derived_gamma_room_ids"] == [1]
    assert derivation["rhs"] == 1
    assert derivation["rhs"] < len(derivation["witness_room_ids"])
    assert derivation["term_count"] == 3
    assert derivation["strengthened"] is True
    assert check_contextual_hall_derivation(
        inst,
        certificate.to_dict(),
        derivation,
    ).valid


def test_decomposition_signal_and_selected_neighborhood_preserve_lineage() -> None:
    inst, certificate, derivation = _generated_lineage()
    report = {
        "rounds": [
            {
                "room_subproblem": {"certificates": [certificate]},
                "room_cuts": [derivation],
            }
        ]
    }
    signals = certificate_signals_from_decomposition(report)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.certificate_id == certificate["certificate_id"]
    assert signal.cut_id == derivation["cut_id"]
    assert signal.derivation_id == derivation["derivation_id"]
    assert signal.metadata["candidate_room_ids"] == [1]
    assert signal.metadata["witness_room_ids"] == [1]
    assert signal.metadata["cut_proof_rule"] == derivation["proof_rule"]
    assert signal.metadata["cut_proof_assumptions"]["counted_starts"]

    initial = {
        activity_id: {**info, "room_id": 1}
        for activity_id, info in _schedule(duration=2).items()
    }
    engine = CertificateGuidedAdaptiveLNS(
        inst,
        neighborhood_sizes=(1,),
        random_seed=7,
    )
    result = engine.run(
        initial,
        score_fn=lambda _schedule: 0,
        validate_fn=lambda _schedule: [],
        repair_fn=lambda _ids, _incumbent, _seconds, _seed: RepairOutcome(
            schedule=None,
            score=None,
            elapsed_seconds=0.001,
            status="INFEASIBLE",
            validated=False,
        ),
        total_seconds=0.2,
        max_rounds=1,
        initial_certificates=signals,
    )
    row = result.trace[0]
    assert row["source_certificate_ids"] == [certificate["certificate_id"]]
    assert row["source_cut_ids"] == [derivation["cut_id"]]
    assert row["source_derivation_ids"] == [derivation["derivation_id"]]
    assert row["source_lineage"][0]["activity_ids"] == [1, 2]
