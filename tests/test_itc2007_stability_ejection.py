from __future__ import annotations

import itertools
import time

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_stability_ejection import (
    _State,
    optimize_itc2007_stability_ejection,
)
from utils.specs import validate_schedule_against_instance


def _instance():
    allowed = {
        "A": {0, 4, 5},
        "B": {0, 1},
        "C": {1, 2},
        "D": {2, 3},
        "E": {3},
    }
    unavailability = tuple(
        (course, 0, period)
        for course, allowed_periods in allowed.items()
        for period in range(6)
        if period not in allowed_periods
    )
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="support-preserving-stability-ejection",
            days=1,
            periods_per_day=6,
            courses=(
                ITC2007Course("A", "TA", 3, 1, 10),
                ITC2007Course("B", "TB", 1, 1, 10),
                ITC2007Course("C", "TC", 1, 1, 10),
                ITC2007Course("D", "TD", 1, 1, 10),
                ITC2007Course("E", "TE", 1, 1, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={"Q": ("B", "C", "D")},
            unavailability=unavailability,
        )
    )


def _by_code(inst) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        code = str(inst.courses[int(activity.course_id)].code)
        grouped.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in grouped.items()}


def _schedule(inst) -> dict[int, dict]:
    by_code = _by_code(inst)
    a1, a2, a3 = by_code["A"]
    placement = {
        a1: (0, 2),
        a2: (4, 1),
        a3: (5, 1),
        by_code["B"][0]: (0, 1),
        by_code["C"][0]: (1, 1),
        by_code["D"][0]: (2, 1),
        by_code["E"][0]: (3, 2),
    }
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        period, room_id = placement[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(period),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _blocker_priority_instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="representation-driven-blocker-priority",
            days=1,
            periods_per_day=8,
            courses=(
                ITC2007Course("T", "TT", 4, 1, 10),
                ITC2007Course("B", "TB", 1, 1, 10),
                ITC2007Course("Q", "TQ", 1, 1, 10),
                ITC2007Course("D", "TD", 1, 1, 10),
                ITC2007Course("E", "TE", 1, 1, 10),
                ITC2007Course("X", "TX", 1, 1, 10),
                ITC2007Course("Y", "TY", 1, 1, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={
                "target-neighbors": ("T", "X", "Y"),
                "blocker-neighbors": ("B", "D", "E"),
            },
            unavailability=(),
        )
    )


def _blocker_priority_schedule(inst) -> dict[int, dict]:
    by_code = _by_code(inst)
    room_by_name = {str(room.name): int(room_id) for room_id, room in inst.rooms.items()}
    t1, t2, t3, t4 = by_code["T"]
    placement = {
        t1: (0, room_by_name["R1"]),
        t2: (1, room_by_name["R1"]),
        t3: (6, room_by_name["R2"]),
        t4: (7, room_by_name["R2"]),
        by_code["B"][0]: (0, room_by_name["R2"]),
        by_code["Q"][0]: (1, room_by_name["R2"]),
        by_code["X"][0]: (2, room_by_name["R2"]),
        by_code["Y"][0]: (3, room_by_name["R2"]),
        by_code["D"][0]: (4, room_by_name["R1"]),
        by_code["E"][0]: (5, room_by_name["R1"]),
    }
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        period, room_id = placement[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(period),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _fragmentation_priority_instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="representation-driven-fragmentation-priority",
            days=1,
            periods_per_day=8,
            courses=(
                ITC2007Course("A", "TA", 4, 1, 10),
                ITC2007Course("B", "TB", 4, 1, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={},
            unavailability=(),
        )
    )


def _fragmentation_priority_schedule(inst) -> dict[int, dict]:
    by_code = _by_code(inst)
    room_by_name = {str(room.name): int(room_id) for room_id, room in inst.rooms.items()}
    placement = {
        by_code["A"][0]: (0, room_by_name["R1"]),
        by_code["A"][1]: (1, room_by_name["R1"]),
        by_code["A"][2]: (2, room_by_name["R1"]),
        by_code["A"][3]: (3, room_by_name["R2"]),
        by_code["B"][0]: (4, room_by_name["R1"]),
        by_code["B"][1]: (5, room_by_name["R1"]),
        by_code["B"][2]: (6, room_by_name["R2"]),
        by_code["B"][3]: (7, room_by_name["R2"]),
    }
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        period, room_id = placement[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(period),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _solve(inst, incumbent, *, seed: int = 17):
    return optimize_itc2007_stability_ejection(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=seed,
        max_target_courses=1,
        max_frontier_courses=4,
        max_frontier_activities=6,
        max_frontier_depth=1,
        max_moved_activities=4,
        max_solve_seconds=0.8,
        max_seconds_per_target=0.8,
    )


def test_atomic_ejection_crosses_every_proper_subset_barrier() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    initial = score_itc2007_instance_schedule(inst, incumbent)

    result = _solve(inst, incumbent)

    assert result.status == "improved"
    assert result.improved
    assert result.initial_score == initial
    assert result.final_score is not None
    assert result.final_score.total == 0
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert score_itc2007_instance_schedule(inst, result.schedule) == result.final_score
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 1
    assert result.telemetry.accepted_candidates == 1

    trajectory = result.telemetry.best_trajectory[0]
    assert trajectory["atomic"] is True
    assert trajectory["target_course"] == "A"
    assert trajectory["frontier_courses"] == ["A", "B", "C", "D"]
    changes = trajectory["changes"]
    assert len(changes) == 4
    assert sum(bool(change["room_changed"]) for change in changes) == 1
    assert sum(bool(change["time_changed"]) for change in changes) == 3

    # No proper subset is a strict hard-valid improvement.  The room
    # consolidation and all three displacements must be accepted atomically.
    for subset_size in range(1, len(changes)):
        for subset in itertools.combinations(changes, subset_size):
            candidate = {activity_id: dict(row) for activity_id, row in incumbent.items()}
            for change in subset:
                activity_id = int(change["activity_id"])
                period = int(change["to_period"])
                candidate[activity_id]["day"] = "D0"
                candidate[activity_id]["slot"] = period
                candidate[activity_id]["room_id"] = int(change["to_room"])
            errors = validate_schedule_against_instance(
                inst,
                candidate,
                strict_rooms=True,
                require_all_activities=True,
            )
            if not errors:
                assert score_itc2007_instance_schedule(inst, candidate).total >= initial.total


def test_frontier_preserves_outside_placements_and_incumbent_room_supports() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    by_code = _by_code(inst)

    result = _solve(inst, incumbent)

    assert result.improved
    outside = by_code["E"][0]
    assert result.schedule[outside] == incumbent[outside]
    for code in ("B", "C", "D"):
        activity_id = by_code[code][0]
        assert result.schedule[activity_id]["room_id"] == incumbent[activity_id]["room_id"]
    target_rooms = {
        int(result.schedule[activity_id]["room_id"])
        for activity_id in by_code["A"]
    }
    assert target_rooms == {1}

    attempt = result.telemetry.attempts[0]
    assert attempt["direct_room_blockers"] == ["B"]
    assert attempt["conflict_courses"] == ["C", "D"]
    assert attempt["frontier_activity_count"] == 6
    assert attempt["score_parity"] is True
    assert attempt["deadline_overrun_seconds"] == 0.0


def test_tie_orientation_and_frontier_follow_blocker_representation() -> None:
    inst = _blocker_priority_instance()
    incumbent = _blocker_priority_schedule(inst)
    assert not validate_schedule_against_instance(
        inst,
        incumbent,
        strict_rooms=True,
        require_all_activities=True,
    )
    state = _State(inst, incumbent)

    targets = state.fragmented_targets()

    assert len(targets) == 1
    target = targets[0]
    assert target.course_code == "T"
    assert inst.rooms[target.primary_room].name == "R2"
    assert state._target_conflict_room_affinity(target) == 2

    frontier = state.build_frontier(
        target,
        max_courses=5,
        max_activities=12,
        max_depth=1,
        deadline=time.perf_counter() + 0.5,
    )

    assert frontier is not None
    assert frontier.direct_room_blockers == ("B", "Q")
    assert set(frontier.conflict_courses) == {"D", "E"}
    assert set(frontier.courses) == {"T", "B", "Q", "D", "E"}
    assert not ({"X", "Y"} & set(frontier.courses))


def test_course_ranking_prefers_more_fragmentation_after_safe_orientation() -> None:
    inst = _fragmentation_priority_instance()
    incumbent = _fragmentation_priority_schedule(inst)
    assert not validate_schedule_against_instance(
        inst,
        incumbent,
        strict_rooms=True,
        require_all_activities=True,
    )

    targets = _State(inst, incumbent).fragmented_targets()

    assert [target.course_code for target in targets] == ["B", "A"]
    by_course = {target.course_code: target for target in targets}
    assert inst.rooms[by_course["A"].primary_room].name == "R1"
    assert len(by_course["A"].minority_activities) == 1
    assert len(by_course["B"].minority_activities) == 2


def test_same_seed_replays_the_same_atomic_candidate() -> None:
    inst = _instance()
    incumbent = _schedule(inst)

    left = _solve(inst, incumbent, seed=991)
    right = _solve(inst, incumbent, seed=991)

    assert left.status == right.status == "improved"
    assert left.schedule == right.schedule
    assert left.initial_score == right.initial_score
    assert left.final_score == right.final_score
    assert left.telemetry.best_trajectory == right.telemetry.best_trajectory


def test_expired_deadline_returns_the_exact_incumbent_without_validation() -> None:
    inst = _instance()
    incumbent = _schedule(inst)

    result = optimize_itc2007_stability_ejection(
        inst,
        incumbent,
        deadline=time.perf_counter() - 0.001,
        seed=17,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 0


def test_deadline_crossed_during_candidate_validation_discards_candidate() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    validation_calls = 0

    def slow_candidate_validation(instance, candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls > 1:
            time.sleep(0.08)
        return validate_schedule_against_instance(
            instance,
            dict(candidate),
            strict_rooms=True,
            require_all_activities=True,
        )

    result = optimize_itc2007_stability_ejection(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.06,
        seed=17,
        max_target_courses=1,
        max_frontier_courses=4,
        max_frontier_activities=6,
        max_frontier_depth=1,
        max_moved_activities=4,
        max_solve_seconds=0.05,
        max_seconds_per_target=0.05,
        completion_reserve_seconds=0.0,
        validator=slow_candidate_validation,
    )

    assert result.status == "deadline_exhausted"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.deadline_overrun_seconds > 0.0


def test_invalid_candidate_and_invalid_bounds_fail_closed() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    validation_calls = 0

    def reject_candidate(instance, candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls > 1:
            return ["independent rejection"]
        return validate_schedule_against_instance(
            instance,
            dict(candidate),
            strict_rooms=True,
            require_all_activities=True,
        )

    rejected = optimize_itc2007_stability_ejection(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_target_courses=1,
        max_frontier_courses=4,
        max_frontier_activities=6,
        max_frontier_depth=1,
        max_moved_activities=4,
        max_seconds_per_target=0.8,
        validator=reject_candidate,
    )
    invalid_bounds = optimize_itc2007_stability_ejection(
        inst,
        incumbent,
        deadline=time.perf_counter() + 1.0,
        max_frontier_courses=0,
    )

    assert rejected.status == "no_improvement"
    assert not rejected.improved
    assert rejected.schedule == incumbent
    assert rejected.telemetry.attempts[0]["status"] == "invalid_candidate"
    assert invalid_bounds.status == "ineligible"
    assert invalid_bounds.schedule == incumbent
    assert invalid_bounds.eligibility_reasons == ("search_bounds_must_be_positive",)


def test_already_stable_schedule_is_returned_unchanged() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    by_code = _by_code(inst)
    final_period = {"B": 1, "C": 2, "D": 3}
    for activity_id in by_code["A"]:
        incumbent[activity_id]["room_id"] = 1
    for code, period in final_period.items():
        incumbent[by_code[code][0]]["slot"] = period

    assert not validate_schedule_against_instance(
        inst,
        incumbent,
        strict_rooms=True,
        require_all_activities=True,
    )
    result = optimize_itc2007_stability_ejection(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
    )

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.initial_score == result.final_score
