from __future__ import annotations

import time

from benchmarks.itc2019 import (
    ITC2019Class,
    ITC2019ClassPlacement,
    ITC2019Configuration,
    ITC2019Course,
    ITC2019Distribution,
    ITC2019OptimizationWeights,
    ITC2019Problem,
    ITC2019Room,
    ITC2019RoomOption,
    ITC2019Subpart,
    ITC2019TimeOption,
    score_itc2019_solution,
    validate_itc2019_solution,
)
from benchmarks.itc2019_global_quality import improve_itc2019_global_recurrence


def _recurrence_problem() -> ITC2019Problem:
    classes = []
    for index, (class_id, week, start, room_id) in enumerate(
        (
            ("A", "100", 0, "R1"),
            ("B", "010", 4, "R2"),
            ("C", "001", 8, "R3"),
        )
    ):
        classes.append(
            ITC2019Class(
                id=class_id,
                limit=10,
                parent_id=None,
                room_required=True,
                time_options=(
                    ITC2019TimeOption("10", start, 2, week, 0),
                    ITC2019TimeOption("10", 12, 2, week, index + 1),
                ),
                room_options=tuple(
                    ITC2019RoomOption(candidate, 0) for candidate in ("R1", "R2", "R3")
                ),
            )
        )
    return ITC2019Problem(
        name="recurrence-quality-toy",
        nr_days=2,
        slots_per_day=20,
        nr_weeks=3,
        optimization=ITC2019OptimizationWeights(
            time=2,
            room=1,
            distribution=5,
            student=0,
        ),
        rooms=tuple(
            ITC2019Room(room_id, 100, (), ()) for room_id in ("R1", "R2", "R3")
        ),
        courses=tuple(
            ITC2019Course(
                f"course-{klass.id}",
                (
                    ITC2019Configuration(
                        f"configuration-{klass.id}",
                        (
                            ITC2019Subpart(
                                f"subpart-{klass.id}",
                                (klass,),
                            ),
                        ),
                    ),
                ),
            )
            for klass in classes
        ),
        distributions=(
            ITC2019Distribution(
                "SameTime",
                False,
                10,
                ("A", "B", "C"),
            ),
            ITC2019Distribution(
                "SameRoom",
                False,
                10,
                ("A", "B", "C"),
            ),
        ),
        students=(),
        source_path="recurrence-quality-toy.xml",
    )


def _incumbent() -> tuple[ITC2019ClassPlacement, ...]:
    return (
        ITC2019ClassPlacement("A", "10", 0, "100", "R1"),
        ITC2019ClassPlacement("B", "10", 4, "010", "R2"),
        ITC2019ClassPlacement("C", "10", 8, "001", "R3"),
    )


def test_global_recurrence_quality_improves_joint_time_and_room_groups() -> None:
    problem = _recurrence_problem()
    incumbent = _incumbent()
    diagnostics: dict[str, object] = {}

    improved = improve_itc2019_global_recurrence(
        problem,
        incumbent,
        {},
        deadline=time.monotonic() + 8.0,
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert validate_itc2019_solution(problem, improved, {}) == []
    assert (
        score_itc2019_solution(problem, improved, {}).total
        < score_itc2019_solution(
            problem,
            incumbent,
            {},
        ).total
    )
    assert {placement.start for placement in improved} == {12}
    assert len({placement.room_id for placement in improved}) == 1
    assert diagnostics["accepted_checkpoints"] >= 2
    assert incumbent == _incumbent()


def test_global_recurrence_quality_preserves_incumbent_without_headroom() -> None:
    problem = _recurrence_problem()
    incumbent = _incumbent()
    diagnostics: dict[str, object] = {}

    result = improve_itc2019_global_recurrence(
        problem,
        incumbent,
        {},
        deadline=time.monotonic() + 0.1,
        workers=1,
        diagnostics=diagnostics,
    )

    assert result == incumbent
    assert diagnostics["skipped"] == "insufficient_finalization_headroom"
    assert (
        diagnostics["final_score"]
        == score_itc2019_solution(
            problem,
            incumbent,
            {},
        ).total
    )


def test_global_recurrence_quality_rolls_back_when_domain_build_expires(
    monkeypatch,
) -> None:
    problem = _recurrence_problem()
    incumbent = _incumbent()
    diagnostics: dict[str, object] = {}

    def expire(*_args, **_kwargs):
        raise TimeoutError("synthetic domain deadline")

    monkeypatch.setattr(
        "benchmarks.itc2019_global_quality._build_factorized_domains",
        expire,
    )
    result = improve_itc2019_global_recurrence(
        problem,
        incumbent,
        {},
        deadline=time.monotonic() + 8.0,
        diagnostics=diagnostics,
    )

    assert result == incumbent
    assert diagnostics["skipped"] == "domain_build:TimeoutError"
