from __future__ import annotations

import csv
import random
from pathlib import Path

from services.contracts import SolveOptions
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import solve_instance
from utils.io import read_schedule_csv_mapped
from utils.specs import validate_schedule_against_instance


def _valid_mapping() -> dict[str, str]:
    return {
        "activity_id": "Activity ID",
        "week": "Week",
        "day": "Day",
        "slot": "Slot",
        "duration": "Duration",
        "course_id": "Course ID",
        "kind": "Kind",
        "staff_id": "Staff ID",
        "room_id": "Room ID",
        "group_ids": "Groups",
    }


def test_mapped_csv_import_fuzz_roundtrip_valid_rows(tmp_path: Path):
    rng = random.Random(0)
    mapping = _valid_mapping()
    valid_days = ["MON", "TUE", "WED", "THU", "FRI"]
    valid_kinds = ["LEC", "TUT", "LAB"]
    for case_idx in range(25):
        path = tmp_path / f"fuzz_valid_{case_idx}.csv"
        rows = []
        row_count = rng.randint(1, 6)
        for activity_id in range(1, row_count + 1):
            rows.append(
                {
                    "Activity ID": str(activity_id),
                    "Week": str(rng.randint(1, 12)),
                    "Day": rng.choice(valid_days),
                    "Slot": str(rng.randint(0, 4)),
                    "Duration": str(rng.randint(1, 3)),
                    "Course ID": str(rng.randint(1, 12)),
                    "Kind": rng.choice(valid_kinds),
                    "Staff ID": str(rng.randint(1, 8)) if rng.random() > 0.2 else "",
                    "Room ID": str(rng.randint(1, 8)) if rng.random() > 0.2 else "",
                    "Groups": "|".join(str(rng.randint(1, 6)) for _ in range(rng.randint(0, 3))),
                }
            )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(mapping.values()))
            writer.writeheader()
            writer.writerows(rows)
        parsed = read_schedule_csv_mapped(path, field_map=mapping, group_separator="|")
        assert len(parsed) == len(rows)
        for activity_id, info in parsed.items():
            assert int(activity_id) >= 1
            assert str(info["day"]) in valid_days
            assert str(info["kind"]) in valid_kinds


def test_mapped_csv_import_fuzz_rejects_missing_required_mappings(tmp_path: Path):
    path = tmp_path / "missing_required.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Activity ID", "Week", "Day"])
        writer.writeheader()
        writer.writerow({"Activity ID": "1", "Week": "1", "Day": "MON"})

    base = _valid_mapping()
    for key in ["activity_id", "week", "day", "slot", "duration", "course_id", "kind"]:
        broken = dict(base)
        broken[key] = ""
        try:
            read_schedule_csv_mapped(path, field_map=broken)
        except ValueError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError(f"Expected ValueError for missing mapping {key}")


def test_schedule_validation_random_mutations_do_not_crash():
    scenario = build_builtin_product_scenario("small_demo", name="Validation Fuzz")
    inst = compile_scenario_instance(scenario)
    result = solve_instance(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            time_limit_seconds=12.0,
            workers=1,
        ),
    )
    assert result.schedule
    baseline = result.schedule
    rng = random.Random(1)
    day_options = list(inst.days) + ["", "SUN", "INVALID"]

    for _ in range(60):
        mutated = {a_id: dict(info) for a_id, info in baseline.items()}
        a_id = rng.choice(list(mutated.keys()))
        field = rng.choice(
            [
                "week",
                "day",
                "slot",
                "duration",
                "room_id",
                "staff_id",
                "course_id",
                "group_ids",
                "kind",
            ]
        )
        if field == "week":
            mutated[a_id][field] = rng.choice([-1, 0, 1, 99, "x"])
        elif field == "day":
            mutated[a_id][field] = rng.choice(day_options)
        elif field == "slot":
            mutated[a_id][field] = rng.choice([-3, -1, 0, inst.slots_per_day, "oops"])
        elif field == "duration":
            mutated[a_id][field] = rng.choice([0, -1, 1, 4, "dur"])
        elif field == "room_id":
            mutated[a_id][field] = rng.choice([None, -1, 9999, "room"])
        elif field == "staff_id":
            mutated[a_id][field] = rng.choice([None, -1, 9999, "staff"])
        elif field == "course_id":
            mutated[a_id][field] = rng.choice([-1, 9999, "course"])
        elif field == "group_ids":
            mutated[a_id][field] = rng.choice([[], [9999], ["x"], "bad"])
        elif field == "kind":
            mutated[a_id][field] = rng.choice(["LEC", "TUT", "LAB", "BAD"])

        errors = validate_schedule_against_instance(
            inst,
            mutated,
            strict_rooms=True,
            require_all_activities=False,
        )
        assert isinstance(errors, list)
        assert all(isinstance(err, str) for err in errors)
