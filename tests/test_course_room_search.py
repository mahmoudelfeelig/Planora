from __future__ import annotations

import copy
import itertools
import time
from pathlib import Path

from benchmarks.itc2007 import (
    convert_itc2007_to_instance,
    parse_itc2007_ctt,
    score_itc2007_instance_schedule,
)
from core.course_room_search import optimize_course_rooms
from utils.specs import validate_schedule_against_instance


TWO_COURSE_INSTANCE = """\
Name: course-room-search
Courses: 2
Rooms: 2
Days: 1
Periods_per_day: 4
Curricula: 0
Constraints: 0
COURSES:
A TA 2 1 10
B TB 2 1 10
ROOMS:
R1 20
R2 20
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def _instance(tmp_path: Path):
    source = tmp_path / "course-room.ctt"
    source.write_text(TWO_COURSE_INSTANCE, encoding="utf-8")
    return convert_itc2007_to_instance(parse_itc2007_ctt(source))


def _activities_by_code(inst) -> dict[str, tuple[int, ...]]:
    result: dict[str, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        code = str(inst.courses[int(activity.course_id)].code)
        result.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in result.items()}


def _schedule(inst, placements: dict[int, tuple[int, int]]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        slot, room_id = placements[int(activity_id)]
        result[int(activity_id)] = {
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
    return result


def _ejection_incumbent(inst) -> dict[int, dict]:
    by_code = _activities_by_code(inst)
    a1, a2 = by_code["A"]
    b1, b2 = by_code["B"]
    return _schedule(
        inst,
        {
            a1: (0, 1),
            a2: (1, 2),
            b1: (1, 1),
            b2: (2, 2),
        },
    )


def test_ejection_chain_improves_when_direct_recolor_is_infeasible(
    tmp_path: Path,
) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)
    by_code = _activities_by_code(inst)
    direct = copy.deepcopy(incumbent)
    direct[by_code["A"][1]]["room_id"] = 1

    assert any(
        "Room overlap" in error
        for error in validate_schedule_against_instance(
            inst,
            direct,
            strict_rooms=True,
            require_all_activities=True,
        )
    )

    result = optimize_course_rooms(
        inst,
        incumbent,
        seed=17,
        run_constructive=False,
        max_chain_length=2,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.final_score is not None
    assert result.initial_score is not None
    assert result.final_score.total < result.initial_score.total
    assert result.telemetry.chain_displacements >= 1
    assert result.telemetry.maximum_chain_length == 2
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert result.schedule[by_code["A"][1]]["room_id"] == 1
    assert result.schedule[by_code["B"][0]]["room_id"] == 2


def test_course_coloring_constructs_consistent_rooms(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    by_code = _activities_by_code(inst)
    a1, a2 = by_code["A"]
    b1, b2 = by_code["B"]
    incumbent = _schedule(
        inst,
        {
            a1: (0, 1),
            a2: (1, 2),
            b1: (2, 2),
            b2: (3, 1),
        },
    )

    result = optimize_course_rooms(
        inst,
        incumbent,
        seed=11,
        run_ejection_chains=False,
    )

    assert result.status == "improved"
    assert result.telemetry.courses_colored == 2
    assert result.telemetry.period_matchings == 4
    for activity_ids in by_code.values():
        assert (
            len(
                {
                    int(result.schedule[activity_id]["room_id"])
                    for activity_id in activity_ids
                }
            )
            == 1
        )


def test_exhaustive_tiny_assignments_are_feasible_and_never_worsen(
    tmp_path: Path,
) -> None:
    inst = _instance(tmp_path)
    by_code = _activities_by_code(inst)
    activity_ids = tuple(sorted(inst.activities))
    slots = {
        by_code["A"][0]: 0,
        by_code["A"][1]: 1,
        by_code["B"][0]: 2,
        by_code["B"][1]: 3,
    }

    for room_vector in itertools.product((1, 2), repeat=len(activity_ids)):
        incumbent = _schedule(
            inst,
            {
                activity_id: (slots[activity_id], room_id)
                for activity_id, room_id in zip(activity_ids, room_vector, strict=True)
            },
        )
        before = score_itc2007_instance_schedule(inst, incumbent).total
        result = optimize_course_rooms(inst, incumbent, seed=23)
        after = score_itc2007_instance_schedule(inst, result.schedule).total

        assert result.status in {"improved", "no_improvement"}
        assert after <= before
        assert not validate_schedule_against_instance(
            inst,
            result.schedule,
            strict_rooms=True,
            require_all_activities=True,
        )


def test_all_non_room_fields_and_fixed_starts_are_preserved(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)

    result = optimize_course_rooms(inst, incumbent, seed=17)

    assert result.fixed_starts_preserved
    assert set(result.schedule) == set(incumbent)
    for activity_id in incumbent:
        assert {
            key: value
            for key, value in result.schedule[activity_id].items()
            if key != "room_id"
        } == {
            key: value
            for key, value in incumbent[activity_id].items()
            if key != "room_id"
        }


def test_same_seed_replays_identical_search_decisions(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)

    left = optimize_course_rooms(inst, incumbent, seed=991)
    right = optimize_course_rooms(inst, incumbent, seed=991)

    assert left.status == right.status
    assert left.schedule == right.schedule
    assert left.initial_score == right.initial_score
    assert left.final_score == right.final_score
    assert left.telemetry.primary_rooms == right.telemetry.primary_rooms
    assert left.telemetry.accepted_by_phase == right.telemetry.accepted_by_phase
    assert left.telemetry.trace == right.telemetry.trace


def test_expired_deadline_returns_exact_incumbent(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)

    result = optimize_course_rooms(
        inst,
        incumbent,
        deadline=time.perf_counter() - 1.0,
        seed=17,
    )

    assert result.status == "deadline_exhausted"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.final_score is None


def test_deadline_crossed_inside_validator_discards_all_work(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)

    def slow_validator(instance, candidate):
        time.sleep(0.02)
        return validate_schedule_against_instance(
            instance,
            candidate,
            strict_rooms=True,
            require_all_activities=True,
        )

    result = optimize_course_rooms(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.005,
        seed=17,
        validator=slow_validator,
    )

    assert result.status == "deadline_exhausted"
    assert not result.improved
    assert result.schedule == incumbent


def test_no_improvement_returns_exact_incumbent(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    by_code = _activities_by_code(inst)
    a1, a2 = by_code["A"]
    b1, b2 = by_code["B"]
    incumbent = _schedule(
        inst,
        {
            a1: (0, 1),
            a2: (1, 1),
            b1: (2, 2),
            b2: (3, 2),
        },
    )

    result = optimize_course_rooms(inst, incumbent, seed=31)

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.initial_score == result.final_score


def test_invalid_incumbent_is_returned_unchanged(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)
    by_code = _activities_by_code(inst)
    incumbent[by_code["A"][1]]["room_id"] = 1

    result = optimize_course_rooms(inst, incumbent, seed=17)

    assert result.status == "invalid_incumbent"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.validation_errors


def test_locked_room_and_availability_are_exact_domain_constraints(
    tmp_path: Path,
) -> None:
    inst = _instance(tmp_path)
    by_code = _activities_by_code(inst)
    a1, a2 = by_code["A"]
    b1, b2 = by_code["B"]
    incumbent = _schedule(
        inst,
        {
            a1: (0, 1),
            a2: (1, 2),
            b1: (2, 1),
            b2: (3, 2),
        },
    )
    inst.locked_activities[a1] = {"room_id": 1}
    inst.rooms[1].availability = {("D0", 0), ("D0", 2), ("D0", 3)}

    result = optimize_course_rooms(inst, incumbent, seed=5)

    assert result.status in {"improved", "no_improvement"}
    assert result.schedule[a1]["room_id"] == 1
    assert result.schedule[a2]["room_id"] == 2
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def test_ineligible_non_itc_instance_fails_closed(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _ejection_incumbent(inst)
    inst.sla_targets = {}

    result = optimize_course_rooms(inst, incumbent, seed=7)

    assert result.status == "ineligible"
    assert not result.improved
    assert result.schedule == incumbent
    assert "requires_lossless_itc2007_import" in result.eligibility.reasons
