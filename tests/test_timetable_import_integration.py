from __future__ import annotations

from pathlib import Path

from services.contracts import ImproveOptions, SolveOptions
from services.scenario_service import (
    build_product_scenario_from_instance,
    compile_scenario_instance,
    load_product_scenario,
    save_product_scenario,
)
from services.solver_service import improve_schedule, solve_instance
from services.timetable_import_service import import_timetable_csv
from utils.io import read_scenario, write_scenario
from utils.specs import validate_schedule_against_instance


def test_imported_timetable_csv_solves_improves_and_roundtrips(tmp_path: Path):
    csv_path = tmp_path / "timetable.csv"
    csv_path.write_text(
        "\n".join(
            [
                "week,day,slot,course,major,room,kind",
                "1,Monday,1,CS101,G1,R-Lec,LEC",
                "2,Tuesday,1,CS101,G1,R-Tut,TUT",
                "3,Wednesday,1,CS101,G1,R-Lab,LAB",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    inst, imported_schedule, meta = import_timetable_csv(csv_path)

    assert meta["duplicate_event_rows_skipped"] == 0
    assert inst.hard_constraints["week1_lectures_only"] is False
    assert inst.hard_constraints["force_repeat_weekly_pattern"] is False
    assert inst.hard_constraints["enforce_course_totals"] is False
    assert {row["kind"] for row in imported_schedule.values()} == {"LEC", "TUT", "LAB"}
    assert len({act.prof_id for act in inst.activities.values()}) == 1
    assert len({act.ta_id for act in inst.activities.values()}) == 1

    scenario = build_product_scenario_from_instance(inst, name="Imported Timetable")
    scenario_path = tmp_path / "imported_product.json"
    save_product_scenario(scenario_path, scenario)
    compiled = compile_scenario_instance(load_product_scenario(scenario_path))
    assert compiled.hard_constraints["enforce_course_totals"] is False

    result = solve_instance(
        compiled,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            objective_profile="fast_feasible",
            time_limit_seconds=10.0,
            workers=1,
        ),
    )
    assert result.is_feasible is True
    assert result.schedule
    assert result.hard_conflicts == []

    improved = improve_schedule(
        compiled,
        result.schedule,
        ImproveOptions(iterations=20, max_seconds=0.2),
    )
    assert validate_schedule_against_instance(
        compiled,
        improved,
        strict_rooms=True,
        require_all_activities=True,
    ) == []

    legacy_path = tmp_path / "imported_legacy.json"
    write_scenario(legacy_path, compiled, improved, meta={"name": "imported-flow"})
    restored_inst, restored_schedule, restored_meta = read_scenario(legacy_path)

    assert restored_meta["name"] == "imported-flow"
    assert len(restored_inst.activities) == len(compiled.activities)
    assert restored_schedule == improved


def test_imported_timetable_duplicate_rows_do_not_reach_solver(tmp_path: Path):
    csv_path = tmp_path / "duplicates.csv"
    csv_path.write_text(
        "\n".join(
            [
                "week,day,slot,course,major,room,kind",
                "1,Monday,1,CS101,G1,R-Lec,LEC",
                "1,Monday,1,CS101,G1,R-Lec,LEC",
                "2,Tuesday,1,CS101,G1,R-Tut,TUT",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    inst, schedule, meta = import_timetable_csv(csv_path)

    assert meta["source_events"] == 3
    assert meta["duplicate_event_rows_skipped"] == 1
    assert len(inst.activities) == 2
    assert len(schedule) == 2
