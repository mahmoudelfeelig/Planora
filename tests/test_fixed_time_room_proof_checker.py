from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks.itc2007 import convert_itc2007_to_instance, parse_itc2007_ctt
from core.fixed_time_room_oracle import optimize_fixed_time_rooms
from core.fixed_time_room_proof_checker import (
    verify_fixed_time_room_oracle_result,
)


TWO_LECTURE_INSTANCE = """\
Name: proof-checker-two-lecture
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


def _case(tmp_path: Path):
    source = tmp_path / "proof-checker.ctt"
    source.write_text(TWO_LECTURE_INSTANCE, encoding="utf-8")
    inst = convert_itc2007_to_instance(parse_itc2007_ctt(source))
    incumbent: dict[int, dict[str, object]] = {}
    for slot, activity_id in enumerate(sorted(inst.activities)):
        activity = inst.activities[activity_id]
        incumbent[int(activity_id)] = {
            "week": int(activity.week),
            "day": "D0",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": 1,
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
    result = optimize_fixed_time_rooms(inst, incumbent)
    assert result.status == "improved"
    return inst, incumbent, result.to_dict()


def test_independent_checker_replays_complete_serialized_result(
    tmp_path: Path,
) -> None:
    inst, incumbent, payload = _case(tmp_path)

    serialized = json.loads(json.dumps(payload, sort_keys=True))
    verification = verify_fixed_time_room_oracle_result(inst, incumbent, serialized)

    assert verification.valid, verification.errors
    assert verification.candidate_schedule is not None
    assert verification.capacity_lower_bound == 0
    assert verification.room_lower_bound == 0
    assert all(
        int(row["room_id"]) == 2
        for row in verification.candidate_schedule.values()
    )


def _tamper_candidate_edges(payload: dict[str, object]) -> None:
    certificates = payload["capacity_certificates"]
    assert isinstance(certificates, list)
    certificates[0]["candidate_edges"][0][1][0][1] += 1


def _tamper_row_potential(payload: dict[str, object]) -> None:
    certificates = payload["capacity_certificates"]
    assert isinstance(certificates, list)
    certificates[0]["row_potentials"][0][1] += 1


def _tamper_candidate_room(payload: dict[str, object]) -> None:
    assignments = payload["candidate_room_assignment"]
    assert isinstance(assignments, list)
    assignments[0][1] = 1


def _tamper_capacity_lower_bound(payload: dict[str, object]) -> None:
    payload["capacity_lower_bound"] = int(payload["capacity_lower_bound"]) + 1


def _tamper_room_lower_bound(payload: dict[str, object]) -> None:
    payload["room_lower_bound"] = int(payload["room_lower_bound"]) + 1


def _tamper_proof_status(payload: dict[str, object]) -> None:
    payload["proof_status"] = "one_period_local_optimal"


def _tamper_fixed_time_digest(payload: dict[str, object]) -> None:
    payload["candidate_fixed_time_digest"] = "0" * 64


def _tamper_deadline(payload: dict[str, object]) -> None:
    timing = payload["timing"]
    assert isinstance(timing, dict)
    timing["deadline_supplied"] = True
    timing["deadline_budget_seconds"] = 0.0
    timing["deadline_remaining_seconds"] = 0.0
    timing["deadline_overrun_seconds"] = 0.1


@pytest.mark.parametrize(
    "tamper",
    [
        _tamper_candidate_edges,
        _tamper_row_potential,
        _tamper_candidate_room,
        _tamper_capacity_lower_bound,
        _tamper_room_lower_bound,
        _tamper_proof_status,
        _tamper_fixed_time_digest,
        _tamper_deadline,
    ],
)
def test_independent_checker_fails_closed_on_material_tampering(
    tmp_path: Path,
    tamper,
) -> None:
    inst, incumbent, payload = _case(tmp_path)
    tampered = copy.deepcopy(payload)
    tamper(tampered)

    verification = verify_fixed_time_room_oracle_result(inst, incumbent, tampered)

    assert not verification.valid
    assert verification.errors


def test_independent_checker_rejects_duplicate_assignment_and_missing_schema(
    tmp_path: Path,
) -> None:
    inst, incumbent, payload = _case(tmp_path)
    duplicate = copy.deepcopy(payload)
    rows = duplicate["candidate_room_assignment"]
    assert isinstance(rows, list)
    rows.append(copy.deepcopy(rows[0]))
    missing = copy.deepcopy(payload)
    del missing["objective_digest"]

    duplicate_check = verify_fixed_time_room_oracle_result(
        inst,
        incumbent,
        duplicate,
    )
    missing_check = verify_fixed_time_room_oracle_result(inst, incumbent, missing)

    assert not duplicate_check.valid
    assert "candidate_assignment:duplicate_activity" in duplicate_check.errors
    assert not missing_check.valid
    assert "result:missing_field:objective_digest" in missing_check.errors


def test_zero_local_certificate_state_is_explicitly_not_applicable(
    tmp_path: Path,
) -> None:
    inst, incumbent, payload = _case(tmp_path)
    without_local = copy.deepcopy(payload)
    without_local["one_period_local_optimal"] = False
    without_local["local_certificates"] = []
    without_local["local_certificate_count"] = 0
    without_local["local_certificate_status"] = "not_applicable"
    without_local["local_certificates_checked"] = None

    valid = verify_fixed_time_room_oracle_result(inst, incumbent, without_local)
    assert valid.valid, valid.errors

    vacuous = copy.deepcopy(without_local)
    vacuous["local_certificates_checked"] = True
    vacuous["local_certificate_status"] = "internally_replayed"
    invalid = verify_fixed_time_room_oracle_result(inst, incumbent, vacuous)

    assert not invalid.valid
    assert "local:certificate_status_mismatch" in invalid.errors
    assert "local:certificates_checked_semantics_mismatch" in invalid.errors


def test_certificate_edge_and_potential_mutations_are_all_detected(
    tmp_path: Path,
) -> None:
    inst, incumbent, payload = _case(tmp_path)
    certificates = payload["capacity_certificates"]
    assert isinstance(certificates, list)
    mutation_count = 0
    for certificate_index, certificate in enumerate(certificates):
        for edge_row_index, edge_row in enumerate(certificate["candidate_edges"]):
            for edge_index, _edge in enumerate(edge_row[1]):
                tampered = copy.deepcopy(payload)
                tampered["capacity_certificates"][certificate_index][
                    "candidate_edges"
                ][edge_row_index][1][edge_index][1] += 1
                assert not verify_fixed_time_room_oracle_result(
                    inst,
                    incumbent,
                    tampered,
                ).valid
                mutation_count += 1
        for potential_index, _potential in enumerate(certificate["row_potentials"]):
            tampered = copy.deepcopy(payload)
            tampered["capacity_certificates"][certificate_index]["row_potentials"][
                potential_index
            ][1] += 1
            assert not verify_fixed_time_room_oracle_result(
                inst,
                incumbent,
                tampered,
            ).valid
            mutation_count += 1
        for potential_index, _potential in enumerate(certificate["room_potentials"]):
            tampered = copy.deepcopy(payload)
            tampered["capacity_certificates"][certificate_index]["room_potentials"][
                potential_index
            ][1] += 1
            assert not verify_fixed_time_room_oracle_result(
                inst,
                incumbent,
                tampered,
            ).valid
            mutation_count += 1
    assert mutation_count >= 8


def test_hall_witness_is_replayed_even_for_nonclaiming_ineligible_result(
    tmp_path: Path,
) -> None:
    inst, incumbent, _payload = _case(tmp_path)
    for room in inst.rooms.values():
        room.availability = set()
    result = optimize_fixed_time_rooms(
        inst,
        incumbent,
        validator=lambda _inst, _schedule: [],
    )
    assert result.status == "ineligible"
    payload = result.to_dict()
    assert payload["hall_witnesses"]

    replay = verify_fixed_time_room_oracle_result(inst, incumbent, payload)
    assert not any(error.startswith("hall[") for error in replay.errors)

    tampered = copy.deepcopy(payload)
    tampered["hall_witnesses"][0]["candidate_room_ids"] = [1]
    invalid = verify_fixed_time_room_oracle_result(inst, incumbent, tampered)

    assert "hall[0]:hall_neighborhood_mismatch" in invalid.errors

    bad_deficiency = copy.deepcopy(payload)
    bad_deficiency["hall_witnesses"][0]["deficiency"] += 1
    invalid_deficiency = verify_fixed_time_room_oracle_result(
        inst,
        incumbent,
        bad_deficiency,
    )
    assert "hall[0]:deficiency_mismatch" in invalid_deficiency.errors
