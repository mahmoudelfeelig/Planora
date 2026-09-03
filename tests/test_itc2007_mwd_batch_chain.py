from __future__ import annotations

import copy
import time

import core.itc2007_mwd_batch_chain as chain_module
from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_mwd_batch_chain import optimize_itc2007_mwd_batch_chain
from utils.specs import validate_schedule_against_instance


def _instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="mwd-batch-chain",
            days=3,
            periods_per_day=2,
            courses=(
                ITC2007Course("A", "TA", 3, 3, 10),
                ITC2007Course("B", "TB", 3, 3, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={"Q": ("A", "B")},
            unavailability=(),
        )
    )


def _by_code(instance) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for activity_id, activity in instance.activities.items():
        code = str(instance.courses[int(activity.course_id)].code)
        grouped.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in grouped.items()}


def _schedule(instance) -> dict[int, dict]:
    by_code = _by_code(instance)
    placement = {
        by_code["A"][0]: (0, 0, 1),
        by_code["A"][1]: (0, 1, 1),
        by_code["A"][2]: (1, 0, 2),
        by_code["B"][0]: (1, 1, 1),
        by_code["B"][1]: (2, 0, 1),
        by_code["B"][2]: (2, 1, 1),
    }
    output: dict[int, dict] = {}
    for activity_id, activity in instance.activities.items():
        day, slot, room_id = placement[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": f"D{day}",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
    return output


def test_chain_accepts_strict_valid_stage_and_room_improvements(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    by_code = _by_code(instance)
    first_candidate = copy.deepcopy(incumbent)
    first_candidate[by_code["A"][1]]["day"] = "D2"
    first_candidate[by_code["A"][1]]["slot"] = 0
    first_candidate[by_code["B"][1]]["day"] = "D0"
    first_candidate[by_code["B"][1]]["slot"] = 1
    second_candidate = copy.deepcopy(first_candidate)
    canonical_first = chain_module.canonicalize_itc2007_schedule(
        instance,
        first_candidate,
    )

    round_calls: list[dict[int, dict]] = []

    def round_model(_inst, schedule, *, deadline, cp_seed):
        del deadline, cp_seed
        round_calls.append(copy.deepcopy(schedule))
        candidate = first_candidate if len(round_calls) == 1 else second_candidate
        return copy.deepcopy(candidate), {"status": "optimal", "roots": ["A"]}

    room_candidate = copy.deepcopy(second_candidate)
    for activity_id in by_code["A"]:
        room_candidate[activity_id]["room_id"] = 1

    def room_descent(_inst, schedule, *, deadline, max_sweeps):
        del deadline, max_sweeps
        assert schedule == canonical_first
        return copy.deepcopy(room_candidate), "improved", {"accepted_chains": 1}

    monkeypatch.setattr(chain_module, "_round_model", round_model)
    monkeypatch.setattr(
        chain_module,
        "_course_room_ejection_descent",
        room_descent,
    )

    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 3.0,
        seed=23,
    )

    assert incumbent == before
    assert len(round_calls) == 2
    assert result.status == "improved"
    assert result.improved
    assert result.final_score is not None
    assert (
        result.final_score.total
        < score_itc2007_instance_schedule(
            instance,
            incumbent,
        ).total
    )
    assert not validate_schedule_against_instance(
        instance,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert result.telemetry.validation_calls == 5
    assert result.telemetry.independent_rescores == 5


def test_second_round_receives_accepted_first_round(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    by_code = _by_code(instance)
    first_candidate = copy.deepcopy(incumbent)
    first_candidate[by_code["A"][1]]["day"] = "D2"
    first_candidate[by_code["A"][1]]["slot"] = 0
    first_candidate[by_code["B"][1]]["day"] = "D0"
    first_candidate[by_code["B"][1]]["slot"] = 1
    seen: list[dict[int, dict]] = []

    def round_model(_inst, schedule, *, deadline, cp_seed):
        del deadline, cp_seed
        seen.append(copy.deepcopy(schedule))
        return copy.deepcopy(first_candidate), {"status": "optimal", "roots": ["A"]}

    monkeypatch.setattr(chain_module, "_round_model", round_model)
    monkeypatch.setattr(
        chain_module,
        "_course_room_ejection_descent",
        lambda _inst, schedule, **_kwargs: (
            copy.deepcopy(schedule),
            "local_optimum",
            {},
        ),
    )

    optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 3.0,
    )

    assert len(seen) == 2
    assert seen[1] == chain_module.canonicalize_itc2007_schedule(
        instance,
        first_candidate,
    )


def test_mutating_validator_fails_closed(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)

    def mutating_validator(_inst, schedule):
        schedule[min(schedule)]["day"] = "MUTATED"
        return []

    called = False

    def round_model(*_args, **_kwargs):
        nonlocal called
        called = True
        return copy.deepcopy(incumbent), {}

    monkeypatch.setattr(chain_module, "_round_model", round_model)
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.5,
        validator=mutating_validator,
    )

    assert not called
    assert result.status == "error"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.error == "incumbent:validator_mutated_candidate"


def test_mutating_official_scorer_fails_closed(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    official = score_itc2007_instance_schedule(instance, incumbent)

    def mutating_scorer(_inst, schedule):
        schedule[min(schedule)]["day"] = "MUTATED"
        return official

    monkeypatch.setattr(
        chain_module,
        "score_itc2007_instance_schedule",
        mutating_scorer,
    )
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.5,
    )

    assert result.status == "error"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.error == "incumbent:official_rescore_mutated_candidate"


def test_mutating_round_helper_fails_closed(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)

    def mutating_round(_inst, schedule, *, deadline, cp_seed):
        del deadline, cp_seed
        schedule[min(schedule)]["room_id"] = 2
        return copy.deepcopy(schedule), {"status": "feasible", "roots": ["A"]}

    monkeypatch.setattr(chain_module, "_round_model", mutating_round)
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.5,
    )

    assert incumbent == before
    assert result.status == "error"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.error == "mwd_batch_round_1:helper_mutated_incumbent"


def test_mutating_room_helper_fails_closed(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)

    monkeypatch.setattr(
        chain_module,
        "_round_model",
        lambda _inst, schedule, **_kwargs: (
            copy.deepcopy(schedule),
            {"status": "local_optimum", "roots": []},
        ),
    )

    def mutating_room(_inst, schedule, *, deadline, max_sweeps):
        del deadline, max_sweeps
        schedule[min(schedule)]["room_id"] = 2
        return copy.deepcopy(schedule), "improved", {"accepted_chains": 1}

    monkeypatch.setattr(
        chain_module,
        "_course_room_ejection_descent",
        mutating_room,
    )
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 2.5,
    )

    assert incumbent == before
    assert result.status == "error"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.error == "course_room_ejection_descent:helper_mutated_incumbent"


def test_late_round_is_truthfully_rejected_without_global_rollback(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    clock = [100.0]

    monkeypatch.setattr(
        chain_module.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def late_round(_inst, schedule, *, deadline, cp_seed):
        del cp_seed
        clock[0] = float(deadline) + 0.001
        return copy.deepcopy(schedule), {"status": "feasible", "roots": ["A"]}

    monkeypatch.setattr(chain_module, "_round_model", late_round)
    monkeypatch.setattr(
        chain_module,
        "_course_room_ejection_descent",
        lambda _inst, schedule, **_kwargs: (
            copy.deepcopy(schedule),
            "local_optimum",
            {},
        ),
    )
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=103.0,
    )

    assert incumbent == before
    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    batch_stages = [
        stage
        for stage in result.telemetry.stages
        if stage.get("name", "").startswith("mwd_batch")
    ]
    assert batch_stages
    assert all(
        stage["status"] == "rejected_deadline_exhausted" for stage in batch_stages
    )
    assert all(stage["helper_status"] == "feasible" for stage in batch_stages)
    assert all(not stage.get("accepted", False) for stage in result.telemetry.stages)


def test_final_deadline_exhaustion_rolls_back_accepted_stage(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    before = copy.deepcopy(incumbent)
    by_code = _by_code(instance)
    first_candidate = copy.deepcopy(incumbent)
    first_candidate[by_code["A"][1]]["day"] = "D2"
    first_candidate[by_code["A"][1]]["slot"] = 0
    first_candidate[by_code["B"][1]]["day"] = "D0"
    first_candidate[by_code["B"][1]]["slot"] = 1
    clock = [100.0]
    validator_calls = [0]

    monkeypatch.setattr(
        chain_module.time,
        "perf_counter",
        lambda: float(clock[0]),
    )

    def round_model(_inst, _schedule_arg, *, deadline, cp_seed):
        del deadline, cp_seed
        return copy.deepcopy(first_candidate), {"status": "optimal", "roots": ["A"]}

    def validator(inst, schedule):
        validator_calls[0] += 1
        errors = validate_schedule_against_instance(
            inst,
            dict(schedule),
            strict_rooms=True,
            require_all_activities=True,
        )
        if validator_calls[0] == 5:
            clock[0] = 103.1
        return errors

    monkeypatch.setattr(chain_module, "_round_model", round_model)
    monkeypatch.setattr(
        chain_module,
        "_course_room_ejection_descent",
        lambda _inst, schedule, **_kwargs: (
            copy.deepcopy(schedule),
            "local_optimum",
            {},
        ),
    )
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=103.0,
        validator=validator,
    )

    assert incumbent == before
    assert validator_calls[0] == 5
    assert any(stage.get("accepted", False) for stage in result.telemetry.stages)
    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert result.deadline_overrun_seconds > 0.0
    assert not result.improved
    assert result.schedule == incumbent


def test_nonexchangeable_import_is_ineligible_before_any_helper(monkeypatch) -> None:
    instance = _instance()
    incumbent = _schedule(instance)
    activity_ids = sorted(instance.activities)
    instance.precedence_rules = [
        {
            "before_activity_id": int(activity_ids[0]),
            "after_activity_id": int(activity_ids[1]),
            "min_gap_slots": 1,
        }
    ]
    called = False

    def round_model(*_args, **_kwargs):
        nonlocal called
        called = True
        return copy.deepcopy(incumbent), {}

    monkeypatch.setattr(chain_module, "_round_model", round_model)
    result = optimize_itc2007_mwd_batch_chain(
        instance,
        incumbent,
        deadline=time.perf_counter() + 0.5,
    )

    assert not called
    assert result.status == "ineligible"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 0
    assert "itc2007_lectures_not_exchangeable" in result.eligibility_reasons


def test_root_selection_is_representation_derived() -> None:
    instance = _instance()
    state = chain_module._State(instance, _schedule(instance))

    roots = chain_module._select_round_roots(state)

    assert set(roots).issubset(state.activities_by_course)
    assert all(state._course_mwd_term(course) > 0 for course in roots)
    expected = tuple(
        sorted(
            (
                course
                for course in state.activities_by_course
                if state._course_mwd_term(course) > 0
            ),
            key=lambda course: (
                -int(state._course_mwd_term(course)),
                sum(
                    len(state.activities_by_course[value])
                    for value in {course, *state.conflict_neighbors[course]}
                ),
                str(course),
            ),
        )[: chain_module.ROOTS_PER_ROUND]
    )
    assert roots == expected
