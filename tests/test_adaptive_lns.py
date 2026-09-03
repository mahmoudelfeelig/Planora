from __future__ import annotations

import core.adaptive_lns as adaptive_lns
from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
)
from core.adaptive_lns import (
    CertificateGuidedAdaptiveLNS,
    CertificateSignal,
    RepairOutcome,
    certificate_signals_from_decomposition,
)
from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember


def _instance() -> Instance:
    return Instance(
        days=["MON", "TUE"],
        slots_per_day=4,
        weeks=[1, 2],
        programs={1: Program(id=1, name="P", course_ids=[1], group_ids=[1])},
        groups={1: Group(id=1, name="G", program_id=1, size=20, course_ids=[1])},
        courses={
            1: Course(
                id=1,
                code="C1",
                name="C1",
                structure_type="LEC_ONLY",
                lecture_count=4,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                prof_id=1,
                ta_id=2,
            )
        },
        staff={
            1: StaffMember(
                id=1,
                name="P",
                is_prof=True,
                available_days={"MON", "TUE"},
                max_slots_per_day=None,
                max_slots_per_week=None,
                can_teach_courses={1},
            ),
            2: StaffMember(
                id=2,
                name="T",
                is_prof=False,
                available_days={"MON", "TUE"},
                max_slots_per_day=None,
                max_slots_per_week=None,
                can_teach_courses={1},
            ),
        },
        rooms={1: Room(id=1, name="R", capacity=30, room_type="LECTURE")},
        activities={
            activity_id: Activity(
                id=activity_id,
                course_id=1,
                week=1 if activity_id <= 2 else 2,
                kind="LEC",
                duration=1,
                group_ids=[1],
                prof_id=1,
                ta_id=2,
            )
            for activity_id in range(1, 5)
        },
    )


def _schedule() -> dict[int, dict[str, object]]:
    return {
        activity_id: {
            "room_id": 1,
            "staff_id": 1,
            "week": 1 if activity_id <= 2 else 2,
            "day": "MON" if activity_id % 2 else "TUE",
            "slot": 3,
            "duration": 1,
            "group_ids": [1],
            "course_id": 1,
            "kind": "LEC",
        }
        for activity_id in range(1, 5)
    }


def test_certificate_guided_adaptive_lns_is_monotone_and_machine_traceable() -> None:
    inst = _instance()
    inst.hard_constraints["enable_context_eligible_adaptive_arms"] = True
    initial = _schedule()
    calls: list[list[int]] = []

    def score(schedule):
        return sum(int(info["slot"]) for info in schedule.values())

    def repair(neighborhood, incumbent, _seconds, _seed):
        calls.append(list(neighborhood))
        candidate = {activity_id: dict(info) for activity_id, info in incumbent.items()}
        target = next(
            (activity_id for activity_id in neighborhood if int(candidate[activity_id]["slot"]) > 0),
            None,
        )
        if target is not None:
            candidate[target]["slot"] = 0
        return RepairOutcome(
            schedule=candidate,
            score=score(candidate),
            elapsed_seconds=0.01,
            status="OPTIMAL",
            validated=True,
            neighborhood_optimal=True,
        )

    engine = CertificateGuidedAdaptiveLNS(
        inst,
        neighborhood_sizes=(2,),
        random_seed=9,
    )
    result = engine.run(
        initial,
        score_fn=score,
        validate_fn=lambda _schedule: [],
        repair_fn=repair,
        total_seconds=1.0,
        slice_seconds=0.1,
        max_rounds=4,
        initial_certificates=[
            CertificateSignal("hall_deficiency", (4,), weight=2.0)
        ],
    )

    assert calls[0][0] == 4
    assert result.final_score <= result.initial_score
    scores_after = [row["score_after"] for row in result.trace]
    assert scores_after == sorted(scores_after, reverse=True)
    assert all(row["validated"] for row in result.trace)
    assert result.certificates_seen == 1
    assert "certificate:2" in result.arm_statistics
    assert "certificate" in result.trace[0]["eligible_families"]


def test_invalid_repair_is_rejected_and_penalized() -> None:
    inst = _instance()
    initial = _schedule()
    engine = CertificateGuidedAdaptiveLNS(inst, neighborhood_sizes=(2,), random_seed=2)

    result = engine.run(
        initial,
        score_fn=lambda schedule: sum(int(info["slot"]) for info in schedule.values()),
        validate_fn=lambda _schedule: [],
        repair_fn=lambda _ids, _schedule, _seconds, _seed: RepairOutcome(
            schedule=None,
            score=None,
            elapsed_seconds=0.01,
            status="INFEASIBLE",
            validated=False,
        ),
        total_seconds=0.2,
        max_rounds=1,
    )

    assert result.final_score == result.initial_score
    assert result.trace[0]["accepted"] is False
    assert result.trace[0]["reward"] < 0


def test_context_eligible_cold_start_skips_absent_certificate_and_boundary_arms() -> None:
    inst = _instance()
    inst.weeks = [1]
    for activity in inst.activities.values():
        activity.week = 1
    inst.hard_constraints["enable_context_eligible_adaptive_arms"] = True
    initial = _schedule()
    for info in initial.values():
        info["week"] = 1
    engine = CertificateGuidedAdaptiveLNS(inst, neighborhood_sizes=(2,), random_seed=3)

    result = engine.run(
        initial,
        score_fn=lambda schedule: sum(int(info["slot"]) for info in schedule.values()),
        validate_fn=lambda _schedule: [],
        repair_fn=lambda _ids, schedule, _seconds, _seed: RepairOutcome(
            schedule={activity_id: dict(info) for activity_id, info in schedule.items()},
            score=sum(int(info["slot"]) for info in schedule.values()),
            elapsed_seconds=0.01,
            status="OPTIMAL",
            validated=True,
            neighborhood_optimal=True,
        ),
        total_seconds=0.1,
        slice_seconds=0.05,
        max_rounds=1,
    )

    row = result.trace[0]
    assert row["arm"] == "penalty:2"
    assert row["eligible_families"] == ["penalty", "random"]
    assert row["source_certificate_ids"] == []


def test_itc2007_penalty_support_uses_official_component_types() -> None:
    problem = ITC2007Problem(
        name="typed-support",
        days=2,
        periods_per_day=3,
        courses=(
            ITC2007Course("C1", "T1", 2, 2, 25),
            ITC2007Course("C2", "T2", 1, 1, 20),
        ),
        rooms=(ITC2007Room("R1", 10), ITC2007Room("R2", 30)),
        curricula={"CUR1": ("C1", "C2")},
        unavailability=(),
    )
    inst = convert_itc2007_to_instance(problem)
    inst.hard_constraints["enable_context_eligible_adaptive_arms"] = True
    c1_ids = sorted(
        activity_id
        for activity_id, activity in inst.activities.items()
        if int(activity.course_id) == 1
    )
    c2_id = next(
        activity_id
        for activity_id, activity in inst.activities.items()
        if int(activity.course_id) == 2
    )
    schedule = {
        c1_ids[0]: {
            "room_id": 1,
            "staff_id": 1,
            "week": 1,
            "day": "D0",
            "slot": 0,
            "duration": 1,
            "group_ids": list(inst.activities[c1_ids[0]].group_ids),
        },
        c1_ids[1]: {
            "room_id": 2,
            "staff_id": 1,
            "week": 1,
            "day": "D0",
            "slot": 2,
            "duration": 1,
            "group_ids": list(inst.activities[c1_ids[1]].group_ids),
        },
        c2_id: {
            "room_id": 2,
            "staff_id": 2,
            "week": 1,
            "day": "D1",
            "slot": 0,
            "duration": 1,
            "group_ids": list(inst.activities[c2_id].group_ids),
        },
    }
    engine = CertificateGuidedAdaptiveLNS(inst, neighborhood_sizes=(2,), random_seed=4)

    support = engine._itc2007_penalty_support(schedule)

    assert support[c1_ids[0]] == {
        "room_capacity": 15,
        "minimum_working_days": 5,
        "curriculum_compactness": 2,
    }
    assert support[c1_ids[1]] == {
        "minimum_working_days": 5,
        "room_stability": 1,
        "curriculum_compactness": 2,
    }
    assert support[c2_id] == {"curriculum_compactness": 2}
    assert engine._penalty_seed_order(schedule) == [c1_ids[0], c1_ids[1], c2_id]

    result = engine.run(
        schedule,
        score_fn=lambda _schedule: 25,
        validate_fn=lambda _schedule: [],
        repair_fn=lambda _ids, incumbent, _seconds, _seed: RepairOutcome(
            schedule={activity_id: dict(info) for activity_id, info in incumbent.items()},
            score=25,
            elapsed_seconds=0.01,
            status="OPTIMAL",
            validated=True,
            neighborhood_optimal=True,
        ),
        total_seconds=0.1,
        slice_seconds=0.05,
        max_rounds=1,
    )
    assert result.trace[0]["arm"] == "penalty:2"
    assert result.trace[0]["seed_activity_ids"] == [c1_ids[0]]
    assert result.trace[0]["seed_support"] == {
        str(c1_ids[0]): support[c1_ids[0]],
    }


def test_decomposition_certificates_become_lns_signals() -> None:
    report = {
        "rounds": [
            {
                "room_subproblem": {
                    "certificates": [
                        {
                            "certificate_type": "hall_deficiency",
                            "activity_ids": [3, 1, 3],
                            "deficiency": 2,
                            "week": 1,
                            "day": "MON",
                            "slot": 2,
                        }
                    ]
                }
            }
        ]
    }

    signals = certificate_signals_from_decomposition(report)
    assert signals == [
        CertificateSignal(
            certificate_type="hall_deficiency",
            activity_ids=(1, 3),
            weight=2.0,
            metadata={"week": 1, "day": "MON", "slot": 2},
        )
    ]


def test_adaptive_slice_never_rounds_past_the_remaining_deadline(monkeypatch) -> None:
    clock = iter((0.0, 0.004, 0.005))
    monkeypatch.setattr(adaptive_lns.time, "perf_counter", lambda: next(clock))
    budgets: list[float] = []

    engine = CertificateGuidedAdaptiveLNS(
        _instance(),
        neighborhood_sizes=(2,),
        random_seed=4,
    )
    result = engine.run(
        _schedule(),
        score_fn=lambda schedule: sum(
            int(info["slot"]) for info in schedule.values()
        ),
        validate_fn=lambda _schedule: [],
        repair_fn=lambda _ids, _schedule, seconds, _seed: (
            budgets.append(float(seconds))
            or RepairOutcome(
                schedule=None,
                score=None,
                elapsed_seconds=float(seconds),
                status="BUDGET_EXHAUSTED",
                validated=False,
            )
        ),
        total_seconds=0.005,
        slice_seconds=1.0,
        max_rounds=1,
    )

    assert len(budgets) == 1
    assert 0.0 < budgets[0] <= 0.001
    assert result.budget_seconds == 0.005
    assert result.trace[0]["slice_budget_seconds"] == budgets[0]
    assert result.trace[0]["remaining_at_start_seconds"] == 0.001
