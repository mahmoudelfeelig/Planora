from __future__ import annotations

import copy
import itertools
import time
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.itc2007 import convert_itc2007_to_instance, parse_itc2007_ctt
from core.fixed_time_room_oracle import (
    RoomOracleDeadline,
    assess_fixed_time_room_eligibility,
    optimize_fixed_time_rooms,
    solve_min_cost_matching,
    solve_period_additive_projection,
    verify_matching_certificate,
)
from core.solver_cp_sat import TimetableSolver
from services import solver_service
from utils.domain import DistributionConstraint
from utils.specs import validate_schedule_against_instance


TWO_LECTURE_INSTANCE = """\
Name: oracle-two-lecture
Courses: 1
Rooms: 2
Days: 1
Periods_per_day: 2
Curricula: 0
Constraints: 0
COURSES:
C1 T1 2 1 25
ROOMS:
R1 10
R2 30
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def _itc_instance(tmp_path: Path):
    source = tmp_path / "oracle.ctt"
    source.write_text(TWO_LECTURE_INSTANCE, encoding="utf-8")
    return convert_itc2007_to_instance(parse_itc2007_ctt(source))


def _schedule(inst, room_ids: tuple[int, int]) -> dict[int, dict[str, object]]:
    rows: dict[int, dict[str, object]] = {}
    for slot, (activity_id, room_id) in enumerate(
        zip(sorted(inst.activities), room_ids, strict=True)
    ):
        activity = inst.activities[activity_id]
        rows[int(activity_id)] = {
            "week": int(activity.week),
            "day": "D0",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
    return rows


def test_hungarian_matches_brute_force_and_replays_dual_certificate() -> None:
    for activity_count in range(1, 4):
        room_count = activity_count + 1
        activity_ids = tuple(range(1, activity_count + 1))
        room_ids = tuple(range(10, 10 + room_count))
        for variant in range(12):
            edges: dict[int, list[tuple[int, int]]] = {}
            for row, activity_id in enumerate(activity_ids):
                values = []
                for column, room_id in enumerate(room_ids):
                    # The first activity_count columns guarantee feasibility;
                    # the remaining partial pattern exercises forbidden edges.
                    if column < activity_count or (row + column + variant) % 3:
                        cost = (7 * row + 5 * column + 3 * variant) % 17
                        values.append((room_id, cost))
                edges[activity_id] = values

            certificate = solve_min_cost_matching(activity_ids, edges)
            costs = {
                activity_id: dict(values) for activity_id, values in edges.items()
            }
            brute = min(
                sum(costs[activity_id][room_id] for activity_id, room_id in zip(activity_ids, rooms, strict=True))
                for rooms in itertools.permutations(room_ids, activity_count)
                if all(
                    room_id in costs[activity_id]
                    for activity_id, room_id in zip(activity_ids, rooms, strict=True)
                )
            )
            assert certificate.checked
            assert certificate.primal_cost == brute
            assert certificate.dual_cost == brute
            assert verify_matching_certificate(activity_ids, edges, certificate).valid


def test_hungarian_certificate_tampering_is_rejected() -> None:
    edges = {1: [(10, 2), (11, 5)], 2: [(10, 4), (11, 1)]}
    certificate = solve_min_cost_matching([1, 2], edges)
    first_activity, first_potential = certificate.row_potentials[0]
    tampered = replace(
        certificate,
        row_potentials=(
            (first_activity, first_potential + 1),
            *certificate.row_potentials[1:],
        ),
    )

    verification = verify_matching_certificate([1, 2], edges, tampered)

    assert not verification.valid
    assert any(
        token in verification.errors
        for token in ("primal_dual_gap", "dual_cost_mismatch")
    )


def test_certificate_replay_rejects_duplicate_rows_and_context_tampering() -> None:
    period = (1, "MON", 0)
    edges = {1: [(10, 2), (11, 5)], 2: [(10, 4), (11, 1)]}
    certificate = solve_min_cost_matching([1, 2], edges, period=period)

    duplicate_assignment = replace(
        certificate,
        assignments=(*certificate.assignments, certificate.assignments[0]),
    )
    duplicate_row_dual = replace(
        certificate,
        row_potentials=(
            *certificate.row_potentials,
            certificate.row_potentials[0],
        ),
    )
    duplicate_room_dual = replace(
        certificate,
        room_potentials=(
            *certificate.room_potentials,
            certificate.room_potentials[0],
        ),
    )
    wrong_period = replace(certificate, period=(1, "MON", 1))
    wrong_method = replace(certificate, method="auction_matching")

    assert "duplicate_assignment_activity" in verify_matching_certificate(
        [1, 2], edges, duplicate_assignment, expected_period=period
    ).errors
    assert "duplicate_row_potential" in verify_matching_certificate(
        [1, 2], edges, duplicate_row_dual, expected_period=period
    ).errors
    assert "duplicate_room_potential" in verify_matching_certificate(
        [1, 2], edges, duplicate_room_dual, expected_period=period
    ).errors
    assert "period_mismatch" in verify_matching_certificate(
        [1, 2], edges, wrong_period, expected_period=period
    ).errors
    assert "method_mismatch" in verify_matching_certificate(
        [1, 2], edges, wrong_method, expected_period=period
    ).errors


def test_dense_matching_deadline_interrupts_normalization_and_digest() -> None:
    size = 500
    edges = {
        activity_id: [
            (room_id, (activity_id * 17 + room_id * 11) % 101)
            for room_id in range(size)
        ]
        for activity_id in range(size)
    }
    started = time.perf_counter()

    with pytest.raises(RoomOracleDeadline):
        solve_min_cost_matching(
            range(size),
            edges,
            deadline=time.perf_counter() + 0.001,
        )

    assert time.perf_counter() - started < 0.10


def test_period_projection_returns_hall_witness() -> None:
    projection = solve_period_additive_projection(
        (1, "MON", 0),
        [1, 2],
        {1: [(10, 0)], 2: [(10, 0)]},
    )

    assert not projection.feasible
    assert projection.certificate is None
    assert projection.hall_witness is not None
    assert projection.hall_witness.activity_ids == (1, 2)
    assert projection.hall_witness.candidate_room_ids == (10,)
    assert projection.hall_witness.deficiency == 1


def test_hall_witness_handles_more_than_one_thousand_alternating_levels() -> None:
    activity_count = 1050
    room_count = activity_count - 1
    edges: dict[int, list[tuple[int, int]]] = {0: [(0, 0)]}
    for activity_id in range(1, activity_count):
        row = [(activity_id - 1, 0)]
        if activity_id < room_count:
            row.append((activity_id, 0))
        edges[activity_id] = row

    projection = solve_period_additive_projection(
        (1, "MON", 0),
        range(activity_count),
        edges,
    )

    assert not projection.feasible
    assert projection.hall_witness is not None
    assert len(projection.hall_witness.activity_ids) == activity_count
    assert len(projection.hall_witness.candidate_room_ids) == room_count
    assert projection.hall_witness.deficiency == 1


def test_eligibility_rejects_repeated_stability_support_key_in_period(
    tmp_path: Path,
) -> None:
    inst = _itc_instance(tmp_path)
    schedule = _schedule(inst, (1, 2))
    second_activity = sorted(schedule)[1]
    schedule[second_activity]["slot"] = 0

    eligibility = assess_fixed_time_room_eligibility(inst, schedule)

    assert not eligibility.eligible
    assert any(
        reason.startswith("multiple_stability_support_activities_in_period")
        for reason in eligibility.reasons
    )


def test_oracle_finds_and_proves_global_capacity_stability_optimum(
    tmp_path: Path,
) -> None:
    inst = _itc_instance(tmp_path)
    incumbent = _schedule(inst, (1, 1))

    result = optimize_fixed_time_rooms(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.best_schedule is not None
    assert result.incumbent_terms is not None
    assert result.candidate_terms is not None
    assert result.incumbent_terms.total == 30
    assert result.candidate_terms.total == 0
    assert result.capacity_lower_bound == 0
    assert result.room_lower_bound == 0
    assert result.global_optimal
    assert result.proof_status == "global_optimal"
    assert result.objective_parity is True
    assert result.fixed_starts_preserved is True
    assert all(certificate.checked for certificate in result.capacity_certificates)
    telemetry = result.to_dict()
    assert telemetry["capacity_certificate_status"] == "internally_replayed"
    assert telemetry["capacity_certificates_checked"] is True
    assert telemetry["capacity_certificates"][0]["row_potentials"]
    assert telemetry["capacity_certificates"][0]["candidate_edges"]
    assert (
        telemetry["capacity_certificates"][0]["method"]
        == "dense_rectangular_hungarian"
    )
    assert validate_schedule_against_instance(
        inst,
        result.best_schedule,
        strict_rooms=True,
        require_all_activities=True,
    ) == []


def test_active_stability_never_overclaims_global_optimality(
    tmp_path: Path,
) -> None:
    inst = _itc_instance(tmp_path)
    # Equal capacities isolate stability; different room locks make a positive
    # stability cost unavoidable, but the conservative additive lower bound is
    # still zero.
    inst.rooms[1].capacity = 30
    inst.rooms[2].capacity = 30
    activity_ids = sorted(inst.activities)
    inst.locked_activities = {
        activity_ids[0]: {"room_id": 1},
        activity_ids[1]: {"room_id": 2},
    }
    incumbent = _schedule(inst, (1, 2))

    result = optimize_fixed_time_rooms(inst, incumbent)

    assert result.status == "no_improvement"
    assert result.candidate_terms is not None
    assert result.candidate_terms.total == 1
    assert result.room_lower_bound == 0
    assert not result.global_optimal
    assert result.one_period_local_optimal
    assert result.proof_status == "one_period_local_optimal"
    assert len(result.local_certificates) == 2
    assert all(certificate.checked for certificate in result.local_certificates)


def test_oracle_rejects_effective_travel_room_coupling(tmp_path: Path) -> None:
    inst = _itc_instance(tmp_path)
    inst.travel_time_rules = {"cross_building": 1}
    inst.hard_constraints["enforce_travel_time_buffers"] = True

    result = optimize_fixed_time_rooms(inst, _schedule(inst, (1, 1)))

    assert result.status == "ineligible"
    assert "travel_room_coupling_requires_general_room_model" in result.eligibility.reasons
    assert result.best_schedule is None


def test_generic_eligibility_rejects_every_room_dependent_distribution_term(
    tmp_path: Path,
) -> None:
    base = _itc_instance(tmp_path)
    base.sla_targets = {}
    base.objective_profile = "balanced"
    schedule = _schedule(base, (1, 1))
    activity_ids = sorted(base.activities)

    for kind in ("same_room", "different_room"):
        inst = copy.deepcopy(base)
        inst.distribution_constraints = [
            DistributionConstraint(
                id=f"soft-{kind}",
                constraint_type=kind,
                activity_ids=activity_ids,
                required=False,
                penalty=7,
            )
        ]

        eligibility = assess_fixed_time_room_eligibility(inst, schedule)

        assert not eligibility.eligible
        assert f"distribution_room_coupling:soft-{kind}:{kind}" in eligibility.reasons

    travel = copy.deepcopy(base)
    travel.travel_time_rules = {"cross_building": 1}
    travel.hard_constraints["enforce_travel_time_buffers"] = True
    travel.distribution_constraints = [
        DistributionConstraint(
            id="soft-same-attendees",
            constraint_type="same_attendees",
            activity_ids=activity_ids,
            required=False,
            penalty=7,
        )
    ]
    eligibility = assess_fixed_time_room_eligibility(travel, schedule)
    assert not eligibility.eligible
    assert "travel_room_coupling_requires_general_room_model" in eligibility.reasons


def test_generic_fairness_first_is_ineligible_until_lexicographic_parity(
    tmp_path: Path,
) -> None:
    inst = _itc_instance(tmp_path)
    inst.sla_targets = {}
    inst.objective_profile = "fairness_first"

    eligibility = assess_fixed_time_room_eligibility(inst, _schedule(inst, (1, 1)))

    assert not eligibility.eligible
    assert (
        "fairness_first_lexicographic_room_objective_not_modeled"
        in eligibility.reasons
    )


def test_expired_deadline_fails_closed_without_candidate(tmp_path: Path) -> None:
    inst = _itc_instance(tmp_path)

    result = optimize_fixed_time_rooms(
        inst,
        _schedule(inst, (1, 1)),
        deadline=time.perf_counter() - 0.001,
    )

    assert result.status == "deadline_exhausted"
    assert result.best_schedule is None
    assert not result.improved
    telemetry = result.to_dict()
    assert telemetry["capacity_certificate_status"] == "not_applicable"
    assert telemetry["capacity_certificates_checked"] is None


def test_validator_overrun_fails_closed_without_candidate(tmp_path: Path) -> None:
    inst = _itc_instance(tmp_path)

    def slow_validator(_inst, _schedule):
        time.sleep(0.02)
        return []

    result = optimize_fixed_time_rooms(
        inst,
        _schedule(inst, (1, 1)),
        deadline=time.perf_counter() + 0.005,
        validator=slow_validator,
    )

    assert result.status == "deadline_exhausted"
    assert result.best_schedule is None
    assert not result.improved


def test_oracle_is_deterministic(tmp_path: Path) -> None:
    inst = _itc_instance(tmp_path)
    incumbent = _schedule(inst, (1, 1))

    first = optimize_fixed_time_rooms(inst, incumbent)
    second = optimize_fixed_time_rooms(inst, incumbent)

    assert first.best_schedule == second.best_schedule
    assert first.selected_start == second.selected_start
    assert [item.domain_digest for item in first.capacity_certificates] == [
        item.domain_digest for item in second.capacity_certificates
    ]


def test_service_uses_oracle_without_reusable_full_cp_model(tmp_path: Path) -> None:
    inst = _itc_instance(tmp_path)
    incumbent = _schedule(inst, (1, 1))

    candidate, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        None,
        budget_seconds=1.0,
        final_deadline=None,
        workers=1,
        seed=17,
    )

    assert meta["status"] == "ACCEPTED_IMPROVEMENT"
    assert meta["returned_source"] == "fixed_time_room_oracle"
    assert meta["oracle"]["proof_status"] == "global_optimal"
    assert meta["oracle"]["objective_parity"] is True
    assert meta["candidate_improvement"] == 30
    assert (
        meta["candidate_room_components"]["room_total"]
        == meta["oracle"]["candidate_terms"]["room_total"]
    )
    assert all(candidate[activity_id]["room_id"] == 2 for activity_id in candidate)


def test_service_rejects_oracle_candidate_returned_after_effective_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inst = _itc_instance(tmp_path)
    incumbent = _schedule(inst, (1, 1))
    completed = optimize_fixed_time_rooms(inst, incumbent)
    assert completed.improved

    def late_oracle(*_args, **_kwargs):
        time.sleep(0.06)
        return completed

    monkeypatch.setattr(solver_service, "optimize_fixed_time_rooms", late_oracle)
    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        None,
        budget_seconds=0.05,
        final_deadline=time.perf_counter() + 0.20,
        workers=1,
        seed=17,
    )

    assert returned is incumbent
    assert meta["status"] == "REJECTED_DEADLINE_OVERRUN"
    assert meta["returned_source"] == "incumbent"
    assert meta["oracle"]["service_acceptance_rejected_deadline"] is True


def test_matched_budget_control_reserves_without_running_an_optimizer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inst = _itc_instance(tmp_path)
    incumbent = _schedule(inst, (1, 1))

    def forbidden_oracle(*_args, **_kwargs):
        raise AssertionError("The matched-budget control must not run the oracle")

    monkeypatch.setattr(
        solver_service,
        "optimize_fixed_time_rooms",
        forbidden_oracle,
    )
    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        None,
        budget_seconds=0.5,
        final_deadline=time.perf_counter() + 1.0,
        workers=1,
        seed=17,
        strategy="control",
    )

    assert returned is incumbent
    assert meta["strategy"] == "control"
    assert meta["status"] == "CONTROL_RESERVE_ONLY"
    assert meta["attempted"] is False
    assert meta["pre_score"] == meta["returned_score"]
    assert meta["incumbent_room_assignment"]


def test_oracle_only_never_falls_through_to_the_full_cp_model(
    tmp_path: Path,
) -> None:
    inst = _itc_instance(tmp_path)
    inst.sla_targets = {}
    inst.objective_profile = "fairness_first"
    incumbent = _schedule(inst, (1, 1))

    class ForbiddenModel:
        room_mode = "cp_rooms"
        use_objective = True

        def __getattr__(self, name):
            raise AssertionError(f"oracle_only unexpectedly used CP method {name}")

    returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        ForbiddenModel(),
        budget_seconds=0.5,
        final_deadline=time.perf_counter() + 1.0,
        workers=1,
        seed=17,
        strategy="oracle_only",
    )

    assert returned is incumbent
    assert meta["strategy"] == "oracle_only"
    assert meta["status"] == "SKIPPED_UNSUPPORTED"
    assert meta["skip_reason"] == "structural_oracle_ineligible"


def test_cp_only_never_invokes_the_structural_oracle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inst = _itc_instance(tmp_path)
    incumbent = _schedule(inst, (1, 1))
    model = TimetableSolver(inst, room_mode="cp_rooms", use_objective=True)

    def forbidden_oracle(*_args, **_kwargs):
        raise AssertionError("cp_only must not run the structural oracle")

    monkeypatch.setattr(
        solver_service,
        "optimize_fixed_time_rooms",
        forbidden_oracle,
    )
    _returned, meta = solver_service._run_fixed_time_room_dive(
        inst,
        incumbent,
        model,
        budget_seconds=0.5,
        final_deadline=time.perf_counter() + 1.0,
        workers=1,
        seed=17,
        strategy="cp_only",
    )

    assert meta["strategy"] == "cp_only"
    assert meta["oracle"]["status"] == "not_requested"
