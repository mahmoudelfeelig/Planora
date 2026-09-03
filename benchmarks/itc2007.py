from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
import re
import subprocess

from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember


@dataclass(frozen=True)
class ITC2007Course:
    name: str
    teacher: str
    lectures: int
    minimum_working_days: int
    students: int


@dataclass(frozen=True)
class ITC2007Room:
    name: str
    capacity: int


@dataclass(frozen=True)
class ITC2007Problem:
    name: str
    days: int
    periods_per_day: int
    courses: tuple[ITC2007Course, ...]
    rooms: tuple[ITC2007Room, ...]
    curricula: dict[str, tuple[str, ...]]
    unavailability: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class ITC2007Score:
    room_capacity: int
    minimum_working_days: int
    curriculum_compactness: int
    room_stability: int
    total: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2007Assignment:
    """One row in the official ITC-2007 curriculum-timetabling output format."""

    course_id: str
    room_id: str
    day: int
    period: int


@dataclass(frozen=True)
class ITC2007Validation:
    """Structured result emitted by the official ITC-2007 C++ validator."""

    lecture_violations: int
    conflict_violations: int
    availability_violations: int
    room_occupation_violations: int
    room_capacity: int
    minimum_working_days: int
    curriculum_compactness: int
    room_stability: int
    total_cost: int
    returncode: int = 0
    stdout: str = field(default="", repr=False, compare=False)
    stderr: str = field(default="", repr=False, compare=False)

    @property
    def hard_violations(self) -> int:
        return int(
            self.lecture_violations
            + self.conflict_violations
            + self.availability_violations
            + self.room_occupation_violations
        )

    @property
    def feasible(self) -> bool:
        return self.hard_violations == 0

    @property
    def soft_score(self) -> ITC2007Score:
        return ITC2007Score(
            room_capacity=int(self.room_capacity),
            minimum_working_days=int(self.minimum_working_days),
            curriculum_compactness=int(self.curriculum_compactness),
            room_stability=int(self.room_stability),
            total=int(self.total_cost),
        )

    def to_dict(self) -> dict[str, int | bool | dict[str, int]]:
        return {
            "lecture_violations": int(self.lecture_violations),
            "conflict_violations": int(self.conflict_violations),
            "availability_violations": int(self.availability_violations),
            "room_occupation_violations": int(self.room_occupation_violations),
            "hard_violations": self.hard_violations,
            "feasible": self.feasible,
            "soft_score": self.soft_score.to_dict(),
            "returncode": int(self.returncode),
        }


class ITC2007ValidatorError(RuntimeError):
    """Raised when the official validator cannot be executed or trusted."""


def parse_itc2007_ctt(path: str | Path) -> ITC2007Problem:
    lines = [line.strip() for line in Path(path).read_text(encoding="utf-8-sig").splitlines()]
    metadata: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    known_sections = {"COURSES", "ROOMS", "CURRICULA", "UNAVAILABILITY_CONSTRAINTS"}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        token = line.rstrip(":").upper()
        if token in known_sections:
            current = token
            sections.setdefault(current, [])
            continue
        if token.rstrip(".") == "END":
            current = None
            continue
        if current is not None:
            sections[current].append(line)
        elif ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip()

    def required_int(key: str) -> int:
        if key not in metadata:
            raise ValueError(f"Missing ITC-2007 metadata field: {key}")
        return int(metadata[key])

    courses: list[ITC2007Course] = []
    for line in sections.get("COURSES", []):
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"Invalid ITC-2007 course row: {line}")
        courses.append(
            ITC2007Course(
                name=fields[0],
                teacher=fields[1],
                lectures=int(fields[2]),
                minimum_working_days=int(fields[3]),
                students=int(fields[4]),
            )
        )

    rooms: list[ITC2007Room] = []
    for line in sections.get("ROOMS", []):
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"Invalid ITC-2007 room row: {line}")
        rooms.append(ITC2007Room(name=fields[0], capacity=int(fields[1])))

    curricula: dict[str, tuple[str, ...]] = {}
    for line in sections.get("CURRICULA", []):
        fields = line.split()
        if len(fields) < 2:
            raise ValueError(f"Invalid ITC-2007 curriculum row: {line}")
        count = int(fields[1])
        members = tuple(fields[2:])
        if len(members) != count:
            raise ValueError(f"Curriculum {fields[0]} declares {count} courses but lists {len(members)}")
        curricula[fields[0]] = members

    unavailability: list[tuple[str, int, int]] = []
    for line in sections.get("UNAVAILABILITY_CONSTRAINTS", []):
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Invalid ITC-2007 unavailability row: {line}")
        unavailability.append((fields[0], int(fields[1]), int(fields[2])))

    expected = {
        "courses": len(courses),
        "rooms": len(rooms),
        "curricula": len(curricula),
        "constraints": len(unavailability),
    }
    for key, actual in expected.items():
        if key in metadata and int(metadata[key]) != actual:
            raise ValueError(f"ITC-2007 {key} count mismatch: header={metadata[key]}, parsed={actual}")

    return ITC2007Problem(
        name=metadata.get("name", Path(path).stem),
        days=required_int("days"),
        periods_per_day=required_int("periods_per_day"),
        courses=tuple(courses),
        rooms=tuple(rooms),
        curricula=curricula,
        unavailability=tuple(unavailability),
    )


def _validate_itc2007_assignments(
    assignments: Sequence[ITC2007Assignment],
    problem: ITC2007Problem,
    *,
    require_complete: bool,
) -> None:
    courses = {course.name: course for course in problem.courses}
    rooms = {room.name for room in problem.rooms}
    for row_number, assignment in enumerate(assignments, start=1):
        if assignment.course_id not in courses:
            raise ValueError(
                f"ITC-2007 solution row {row_number} references unknown course "
                f"{assignment.course_id}"
            )
        if assignment.room_id not in rooms:
            raise ValueError(
                f"ITC-2007 solution row {row_number} references unknown room "
                f"{assignment.room_id}"
            )
        if not 0 <= int(assignment.day) < int(problem.days):
            raise ValueError(
                f"ITC-2007 solution row {row_number} day is outside the declared grid: "
                f"{assignment.day}"
            )
        if not 0 <= int(assignment.period) < int(problem.periods_per_day):
            raise ValueError(
                f"ITC-2007 solution row {row_number} period is outside the declared grid: "
                f"{assignment.period}"
            )

    if require_complete:
        actual = Counter(row.course_id for row in assignments)
        expected = Counter(
            {course.name: int(course.lectures) for course in problem.courses}
        )
        if actual != expected:
            differences = [
                f"{course.name}: expected {course.lectures}, got {actual[course.name]}"
                for course in problem.courses
                if actual[course.name] != int(course.lectures)
            ]
            unexpected = sorted(set(actual) - set(expected))
            differences.extend(f"{name}: unexpected" for name in unexpected)
            raise ValueError(
                "ITC-2007 solution lecture count mismatch: " + "; ".join(differences)
            )


def parse_itc2007_out(
    path: str | Path,
    *,
    problem: ITC2007Problem | None = None,
    require_complete: bool = False,
) -> tuple[ITC2007Assignment, ...]:
    """Parse the official ``Course Room Day Period`` solution format.

    The official format contains no lecture identifier. When a problem is
    supplied, identifiers and grid bounds are checked. ``require_complete``
    additionally requires exactly the declared number of rows per course.
    """

    assignments: list[ITC2007Assignment] = []
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(
                f"Invalid ITC-2007 solution row {line_number}: expected 4 fields, "
                f"got {len(fields)}"
            )
        try:
            day = int(fields[2])
            period = int(fields[3])
        except ValueError as exc:
            raise ValueError(
                f"Invalid ITC-2007 solution row {line_number}: day and period must be integers"
            ) from exc
        assignments.append(
            ITC2007Assignment(
                course_id=fields[0],
                room_id=fields[1],
                day=day,
                period=period,
            )
        )

    if require_complete and problem is None:
        raise ValueError("require_complete=True requires an ITC-2007 problem")
    if problem is not None:
        _validate_itc2007_assignments(
            assignments,
            problem,
            require_complete=require_complete,
        )
    return tuple(assignments)


def _itc2007_schedule_assignments(
    problem: ITC2007Problem,
    inst: Instance,
    schedule: dict[int, dict],
    *,
    require_complete: bool,
) -> tuple[ITC2007Assignment, ...]:
    course_name_by_id = {
        int(course_id): str(course.code) for course_id, course in inst.courses.items()
    }
    problem_courses = {course.name for course in problem.courses}
    if set(course_name_by_id.values()) != problem_courses:
        raise ValueError("Planora instance courses do not match the ITC-2007 problem")

    room_name_by_id = {
        int(room_id): str(room.name) for room_id, room in inst.rooms.items()
    }
    problem_rooms = {room.name for room in problem.rooms}
    if set(room_name_by_id.values()) != problem_rooms:
        raise ValueError("Planora instance rooms do not match the ITC-2007 problem")

    normalized_schedule: dict[int, dict] = {}
    for raw_activity_id, row in schedule.items():
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Planora activity id: {raw_activity_id!r}") from exc
        if activity_id in normalized_schedule:
            raise ValueError(f"Duplicate Planora activity id after normalization: {activity_id}")
        if activity_id not in inst.activities:
            raise ValueError(f"Schedule references unknown Planora activity {activity_id}")
        normalized_schedule[activity_id] = row

    expected_activity_ids = set(inst.activities)
    if require_complete and set(normalized_schedule) != expected_activity_ids:
        missing = sorted(expected_activity_ids - set(normalized_schedule))
        extra = sorted(set(normalized_schedule) - expected_activity_ids)
        raise ValueError(
            f"Incomplete ITC-2007 schedule: missing activities={missing}, extra activities={extra}"
        )

    day_index_by_name = {str(day): index for index, day in enumerate(inst.days)}
    assignments: list[ITC2007Assignment] = []
    for activity_id in sorted(normalized_schedule):
        activity = inst.activities[activity_id]
        row = normalized_schedule[activity_id]
        course_name = course_name_by_id.get(int(activity.course_id))
        if course_name not in problem_courses:
            raise ValueError(
                f"Planora activity {activity_id} has no matching ITC-2007 course"
            )
        if int(row.get("week", activity.week)) != 1:
            raise ValueError(f"ITC-2007 activity {activity_id} must be in week 1")
        day_name = str(row.get("day", ""))
        if day_name not in day_index_by_name:
            raise ValueError(
                f"ITC-2007 activity {activity_id} uses unknown Planora day {day_name!r}"
            )
        try:
            period = int(row["slot"])
            room_id = int(row["room_id"])
        except KeyError as exc:
            raise ValueError(
                f"ITC-2007 activity {activity_id} is missing {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"ITC-2007 activity {activity_id} has a non-integer slot or room id"
            ) from exc
        if room_id not in room_name_by_id:
            raise ValueError(
                f"ITC-2007 activity {activity_id} references unknown Planora room {room_id}"
            )
        assignments.append(
            ITC2007Assignment(
                course_id=course_name,
                room_id=room_name_by_id[room_id],
                day=day_index_by_name[day_name],
                period=period,
            )
        )

    _validate_itc2007_assignments(
        assignments,
        problem,
        require_complete=require_complete,
    )
    return tuple(assignments)


def write_itc2007_solution(
    path: str | Path,
    problem: ITC2007Problem,
    inst: Instance,
    schedule: dict[int, dict],
    *,
    require_complete: bool = True,
) -> None:
    """Write a Planora schedule in the official ITC-2007 ``.out`` format."""

    assignments = _itc2007_schedule_assignments(
        problem,
        inst,
        schedule,
        require_complete=require_complete,
    )
    payload = "".join(
        f"{row.course_id} {row.room_id} {row.day} {row.period}\n"
        for row in assignments
    )
    Path(path).write_text(payload, encoding="utf-8", newline="\n")


def load_itc2007_solution(
    path: str | Path,
    problem: ITC2007Problem,
    inst: Instance,
) -> dict[int, dict]:
    """Load a complete official solution into Planora's schedule representation.

    Since official rows do not identify individual lectures, placements for a
    course are sorted by time and room, then assigned to that course's Planora
    activity ids in ascending order. Thus every official row ordering loads as
    the same strict-start representative used by the CP symmetry formulation.
    """

    assignments = parse_itc2007_out(
        path,
        problem=problem,
        require_complete=True,
    )
    course_name_by_id = {
        int(course_id): str(course.code) for course_id, course in inst.courses.items()
    }
    activity_ids_by_course: dict[str, list[int]] = defaultdict(list)
    for activity_id, activity in inst.activities.items():
        course_name = course_name_by_id.get(int(activity.course_id))
        if course_name is None:
            raise ValueError(
                f"Planora activity {activity_id} references unknown course {activity.course_id}"
            )
        activity_ids_by_course[course_name].append(int(activity_id))
    for activity_ids in activity_ids_by_course.values():
        activity_ids.sort()

    room_id_by_name = {str(room.name): int(room_id) for room_id, room in inst.rooms.items()}
    next_index: Counter[str] = Counter()
    schedule: dict[int, dict] = {}
    canonical_assignments = sorted(
        assignments,
        key=lambda row: (
            str(row.course_id),
            int(row.day),
            int(row.period),
            str(row.room_id),
        ),
    )
    for assignment in canonical_assignments:
        index = next_index[assignment.course_id]
        activity_ids = activity_ids_by_course.get(assignment.course_id, [])
        if index >= len(activity_ids):
            raise ValueError(
                f"Planora instance has too few activities for course {assignment.course_id}"
            )
        activity_id = activity_ids[index]
        activity = inst.activities[activity_id]
        if not 0 <= assignment.day < len(inst.days):
            raise ValueError(
                f"ITC-2007 day {assignment.day} cannot be mapped into the Planora instance"
            )
        if assignment.room_id not in room_id_by_name:
            raise ValueError(
                f"ITC-2007 room {assignment.room_id} cannot be mapped into the Planora instance"
            )
        schedule[activity_id] = {
            "week": 1,
            "day": str(inst.days[assignment.day]),
            "slot": int(assignment.period),
            "duration": int(activity.duration),
            "room_id": room_id_by_name[assignment.room_id],
        }
        next_index[assignment.course_id] += 1

    if set(schedule) != set(inst.activities):
        missing = sorted(set(inst.activities) - set(schedule))
        raise ValueError(f"ITC-2007 solution could not map all Planora activities: {missing}")
    return schedule


def canonicalize_itc2007_schedule(
    inst: Instance,
    schedule: dict[int, dict],
) -> dict[int, dict]:
    """Return the unique start-ordered representative of an ITC-2007 schedule.

    The official format identifies a course placement, not an individual
    lecture.  Imported lectures of one course are therefore exchangeable.  We
    assign their placement rows, sorted by time and room, to ascending Planora
    activity ids.  This changes neither the official ``.out`` row multiset nor
    any official objective component.

    The operation is intentionally restricted to untouched ITC-2007 imports.
    Activity-specific locks, relations, or unequal availability would give the
    synthetic lecture ids semantics that the official problem does not have.
    """

    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007") or not isinstance(
        metadata,
        dict,
    ):
        raise ValueError("Instance is not a metadata-backed ITC-2007 import")
    if str(metadata.get("course_lecture_symmetry", "")) != "strict_start_order":
        raise ValueError("Instance does not declare the ITC-2007 lecture symmetry contract")

    normalized: dict[int, dict] = {}
    for raw_activity_id, row in schedule.items():
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Planora activity id: {raw_activity_id!r}") from exc
        if activity_id in normalized:
            raise ValueError(f"Duplicate Planora activity id after normalization: {activity_id}")
        if activity_id not in inst.activities:
            raise ValueError(f"Schedule references unknown Planora activity {activity_id}")
        if not isinstance(row, dict):
            raise ValueError(f"Schedule row for activity {activity_id} must be a mapping")
        normalized[activity_id] = dict(row)
    if set(normalized) != set(inst.activities):
        missing = sorted(set(inst.activities) - set(normalized))
        extra = sorted(set(normalized) - set(inst.activities))
        raise ValueError(
            f"Canonicalization requires a complete ITC-2007 schedule: "
            f"missing activities={missing}, extra activities={extra}"
        )

    if getattr(inst, "locked_activities", {}) or getattr(inst, "precedence_rules", []):
        raise ValueError("Activity-specific locks or precedence rules break lecture exchangeability")
    if getattr(inst, "distribution_constraints", []):
        raise ValueError("Activity-specific distribution rules break lecture exchangeability")

    day_index = {str(day): index for index, day in enumerate(inst.days)}
    activities_by_course: dict[int, list[int]] = defaultdict(list)
    for activity_id, activity in inst.activities.items():
        activities_by_course[int(activity.course_id)].append(int(activity_id))

    canonical: dict[int, dict] = {}
    unavailability = getattr(inst, "activity_unavailability", {}) or {}
    for course_id, activity_ids in sorted(activities_by_course.items()):
        ordered_ids = sorted(activity_ids)
        signatures = {
            (
                int(activity.week),
                str(activity.kind),
                int(activity.duration),
                tuple(sorted(int(value) for value in activity.group_ids)),
                int(activity.prof_id),
                int(activity.ta_id),
                str(activity.requires_specialization or ""),
                tuple(sorted(int(value) for value in (activity.resource_ids or []))),
                str(activity.cluster_key or ""),
                tuple(
                    sorted(
                        (str(day), int(slot))
                        for day, slot in unavailability.get(int(activity_id), set())
                    )
                ),
            )
            for activity_id in ordered_ids
            for activity in [inst.activities[activity_id]]
        }
        if len(signatures) != 1:
            raise ValueError(
                f"Course {course_id} has non-interchangeable activity-specific data"
            )

        def placement_key(row: dict) -> tuple[int, int, int, int]:
            week = int(row.get("week", inst.activities[ordered_ids[0]].week))
            day = str(row.get("day", ""))
            if day not in day_index:
                raise ValueError(f"ITC-2007 schedule uses unknown day {day!r}")
            try:
                slot = int(row["slot"])
                room_id = int(row["room_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("ITC-2007 schedule rows require integer slot and room_id") from exc
            return week, day_index[day], slot, room_id

        placements = sorted(
            (dict(normalized[activity_id]) for activity_id in ordered_ids),
            key=placement_key,
        )
        for activity_id, row in zip(ordered_ids, placements):
            canonical[int(activity_id)] = row
    return canonical


def convert_itc2007_to_instance(problem: ITC2007Problem) -> Instance:
    days = [f"D{index}" for index in range(problem.days)]
    course_id_by_name = {
        course.name: index for index, course in enumerate(problem.courses, start=1)
    }
    teacher_names = sorted({course.teacher for course in problem.courses})
    teacher_id_by_name = {
        name: index for index, name in enumerate(teacher_names, start=1)
    }
    dummy_ta_id = len(teacher_names) + 1

    enrollment_group_id = {
        course.name: index for index, course in enumerate(problem.courses, start=1)
    }
    curriculum_group_id = {
        name: len(problem.courses) + index
        for index, name in enumerate(sorted(problem.curricula), start=1)
    }
    groups: dict[int, Group] = {}
    for course in problem.courses:
        course_id = course_id_by_name[course.name]
        group_id = enrollment_group_id[course.name]
        groups[group_id] = Group(
            id=group_id,
            name=f"ENROLLMENT-{course.name}",
            program_id=1,
            size=int(course.students),
            course_ids=[course_id],
            preferred_free_days=0,
        )
    for curriculum_name, members in problem.curricula.items():
        group_id = curriculum_group_id[curriculum_name]
        groups[group_id] = Group(
            id=group_id,
            name=curriculum_name,
            program_id=1,
            size=0,
            course_ids=[course_id_by_name[name] for name in members],
            preferred_free_days=0,
        )

    courses = {
        course_id_by_name[row.name]: Course(
            id=course_id_by_name[row.name],
            code=row.name,
            name=row.name,
            structure_type="LEC_ONLY",
            lecture_count=int(row.lectures),
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            prof_id=teacher_id_by_name[row.teacher],
            ta_id=dummy_ta_id,
        )
        for row in problem.courses
    }
    staff: dict[int, StaffMember] = {}
    for teacher_name, teacher_id in teacher_id_by_name.items():
        teachable = {
            course_id_by_name[course.name]
            for course in problem.courses
            if course.teacher == teacher_name
        }
        staff[teacher_id] = StaffMember(
            id=teacher_id,
            name=teacher_name,
            is_prof=True,
            available_days=set(days),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses=teachable,
        )
    staff[dummy_ta_id] = StaffMember(
        id=dummy_ta_id,
        name="ITC2007-UNUSED-TA",
        is_prof=False,
        available_days=set(days),
        max_slots_per_day=None,
        max_slots_per_week=None,
        can_teach_courses=set(courses),
    )

    curricula_by_course: dict[str, list[int]] = {name: [] for name in course_id_by_name}
    for curriculum_name, members in problem.curricula.items():
        for course_name in members:
            curricula_by_course[course_name].append(curriculum_group_id[curriculum_name])
    activities: dict[int, Activity] = {}
    activity_ids_by_course: dict[str, list[int]] = {}
    next_activity_id = 1
    for row in problem.courses:
        activity_ids_by_course[row.name] = []
        group_ids = [enrollment_group_id[row.name], *sorted(curricula_by_course[row.name])]
        for _ in range(int(row.lectures)):
            activity_id = next_activity_id
            next_activity_id += 1
            activity_ids_by_course[row.name].append(activity_id)
            activities[activity_id] = Activity(
                id=activity_id,
                course_id=course_id_by_name[row.name],
                week=1,
                kind="LEC",
                duration=1,
                group_ids=group_ids,
                prof_id=teacher_id_by_name[row.teacher],
                ta_id=dummy_ta_id,
            )

    activity_unavailability: dict[int, set[tuple[str, int]]] = {}
    for course_name, day_index, period in problem.unavailability:
        if course_name not in activity_ids_by_course:
            raise ValueError(f"Unavailability references unknown course {course_name}")
        if not (0 <= day_index < len(days)) or not (0 <= period < problem.periods_per_day):
            raise ValueError(f"Unavailability is outside the declared grid: {(course_name, day_index, period)}")
        for activity_id in activity_ids_by_course[course_name]:
            activity_unavailability.setdefault(activity_id, set()).add((days[day_index], period))

    instance = Instance(
        days=days,
        slots_per_day=int(problem.periods_per_day),
        weeks=[1],
        programs={
            1: Program(
                id=1,
                name=f"ITC2007-{problem.name}",
                course_ids=sorted(courses),
                group_ids=sorted(groups),
            )
        },
        groups=groups,
        courses=courses,
        staff=staff,
        rooms={
            index: Room(
                id=index,
                name=row.name,
                capacity=int(row.capacity),
                room_type="LECTURE",
            )
            for index, row in enumerate(problem.rooms, start=1)
        },
        activities=activities,
        hard_constraints={
            "week1_lectures_only": True,
            "enforce_course_totals": True,
            "enforce_room_capacity": False,
            "enable_context_eligible_adaptive_arms": True,
            # A bounded single-seed diagnostic identified compact (12, 24)
            # arms as a candidate ablation. Keep it off until the full paired
            # ITC-2007 gate establishes robust non-worsening; general instances
            # also retain their configured neighborhood sizes.
            "enable_itc2007_compact_adaptive_arms": False,
            # The strict course-orbit cut is mathematically exact, but the
            # initial comp01 multi-seed pilot did not show a robust speed/quality
            # gain. Keep it as an explicit research ablation until a broader
            # matrix supports enabling it by default.
            "enable_itc2007_course_symmetry": False,
        },
        objective_profile="fairness_first",
        activity_unavailability=activity_unavailability,
        sla_targets={
            "benchmark_family": "ITC-2007 Curriculum Course Timetabling",
            "benchmark_instance": problem.name,
            "translation": "Lossless ITC-2007 curriculum model with the official four-term objective available in CP-room mode",
            "unmapped_soft_constraints": [],
            "minimum_working_days": {
                row.name: int(row.minimum_working_days) for row in problem.courses
            },
            "itc2007": {
                "course_lecture_symmetry": "strict_start_order",
                "objective_weights": {
                    "room_capacity": 1,
                    "minimum_working_days": 5,
                    "curriculum_compactness": 2,
                    "room_stability": 1,
                },
                "course_students": {
                    row.name: int(row.students) for row in problem.courses
                },
                "minimum_working_days": {
                    row.name: int(row.minimum_working_days) for row in problem.courses
                },
                "curricula": {
                    name: list(members) for name, members in problem.curricula.items()
                },
            },
        },
    )
    return instance


def load_itc2007_instance(path: str | Path) -> Instance:
    return convert_itc2007_to_instance(parse_itc2007_ctt(path))


def _score_itc2007_components(
    inst: Instance,
    schedule: dict[int, dict],
    *,
    course_students: dict[str, int],
    minimum_days_by_course: dict[str, int],
    curricula: dict[str, tuple[str, ...]],
    weights: dict[str, int],
) -> ITC2007Score:
    course_name_by_id = {int(course_id): str(course.code) for course_id, course in inst.courses.items()}
    known_courses = set(course_name_by_id.values())
    expected_courses = set(course_students) | set(minimum_days_by_course)
    expected_courses.update(
        str(course_name)
        for members in curricula.values()
        for course_name in members
    )
    unknown_courses = sorted(expected_courses - known_courses)
    if unknown_courses:
        raise ValueError(
            f"ITC-2007 scoring metadata references unknown courses: {unknown_courses}"
        )
    missing_students = sorted(known_courses - set(course_students))
    missing_minimum_days = sorted(known_courses - set(minimum_days_by_course))
    if missing_students or missing_minimum_days:
        raise ValueError(
            "Incomplete ITC-2007 scoring metadata: "
            f"missing course_students={missing_students}, "
            f"missing minimum_working_days={missing_minimum_days}"
        )

    assigned_by_course: dict[str, list[dict]] = {name: [] for name in known_courses}
    for activity_id, info in schedule.items():
        activity = inst.activities.get(int(activity_id))
        if activity is None:
            continue
        name = course_name_by_id.get(int(activity.course_id))
        if name in assigned_by_course:
            assigned_by_course[name].append(info)

    room_capacity = 0
    minimum_working_days = 0
    room_stability = 0
    for name in sorted(known_courses):
        rows = assigned_by_course.get(name, [])
        for row in rows:
            room_id = row.get("room_id")
            capacity = int(inst.rooms[int(room_id)].capacity) if room_id is not None and int(room_id) in inst.rooms else 0
            room_capacity += int(weights["room_capacity"]) * max(
                0,
                int(course_students[name]) - capacity,
            )
        distinct_days = {(int(row["week"]), str(row["day"])) for row in rows}
        minimum_working_days += int(weights["minimum_working_days"]) * max(
            0,
            int(minimum_days_by_course[name]) - len(distinct_days),
        )
        distinct_rooms = {int(row["room_id"]) for row in rows if row.get("room_id") is not None}
        room_stability += int(weights["room_stability"]) * max(
            0,
            len(distinct_rooms) - 1,
        )

    curriculum_compactness = 0
    for members in curricula.values():
        rows = [
            row
            for course_name in members
            for row in assigned_by_course.get(course_name, [])
        ]
        by_day: dict[tuple[int, str], list[dict]] = {}
        for row in rows:
            by_day.setdefault((int(row["week"]), str(row["day"])), []).append(row)
        for day_rows in by_day.values():
            occupied_slots = {int(row["slot"]) for row in day_rows}
            for row in day_rows:
                slot = int(row["slot"])
                if slot - 1 not in occupied_slots and slot + 1 not in occupied_slots:
                    curriculum_compactness += int(weights["curriculum_compactness"])

    total = room_capacity + minimum_working_days + curriculum_compactness + room_stability
    return ITC2007Score(
        room_capacity=int(room_capacity),
        minimum_working_days=int(minimum_working_days),
        curriculum_compactness=int(curriculum_compactness),
        room_stability=int(room_stability),
        total=int(total),
    )


def score_itc2007_schedule(
    problem: ITC2007Problem,
    inst: Instance,
    schedule: dict[int, dict],
) -> ITC2007Score:
    """Return the official ITC-2007 curriculum-timetabling soft score.

    Component weights are applied here: capacity 1, minimum working days 5,
    isolated curriculum lecture 2, and each additional course room 1.
    Hard feasibility remains the responsibility of Planora's validator.
    """

    return _score_itc2007_components(
        inst,
        schedule,
        course_students={course.name: int(course.students) for course in problem.courses},
        minimum_days_by_course={
            course.name: int(course.minimum_working_days) for course in problem.courses
        },
        curricula={name: tuple(members) for name, members in problem.curricula.items()},
        weights={
            "room_capacity": 1,
            "minimum_working_days": 5,
            "curriculum_compactness": 2,
            "room_stability": 1,
        },
    )


def score_itc2007_instance_schedule(
    inst: Instance,
    schedule: dict[int, dict],
) -> ITC2007Score:
    """Score an imported ITC-2007 instance using its persisted official metadata."""

    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007") or not isinstance(
        metadata,
        dict,
    ):
        raise ValueError("Instance does not contain ITC-2007 official scoring metadata")
    raw_weights = dict(metadata.get("objective_weights") or {})
    required_weights = {
        "room_capacity",
        "minimum_working_days",
        "curriculum_compactness",
        "room_stability",
    }
    missing_weights = sorted(required_weights - set(raw_weights))
    if missing_weights:
        raise ValueError(f"ITC-2007 scoring metadata is missing weights: {missing_weights}")
    return _score_itc2007_components(
        inst,
        schedule,
        course_students={
            str(key): int(value)
            for key, value in dict(metadata.get("course_students") or {}).items()
        },
        minimum_days_by_course={
            str(key): int(value)
            for key, value in dict(metadata.get("minimum_working_days") or {}).items()
        },
        curricula={
            str(name): tuple(str(value) for value in list(members or []))
            for name, members in dict(metadata.get("curricula") or {}).items()
        },
        weights={str(key): int(value) for key, value in raw_weights.items()},
    )


_ITC2007_VALIDATOR_FIELDS = {
    "lecture_violations": re.compile(
        r"^\s*Violations of Lectures \(hard\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "conflict_violations": re.compile(
        r"^\s*Violations of Conflicts \(hard\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "availability_violations": re.compile(
        r"^\s*Violations of Availability \(hard\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "room_occupation_violations": re.compile(
        r"^\s*Violations of RoomOccupation \(hard\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "room_capacity": re.compile(
        r"^\s*Cost of RoomCapacity \(soft\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "minimum_working_days": re.compile(
        r"^\s*Cost of MinWorkingDays \(soft\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "curriculum_compactness": re.compile(
        r"^\s*Cost of CurriculumCompactness \(soft\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
    "room_stability": re.compile(
        r"^\s*Cost of RoomStability \(soft\)\s*:\s*(\d+)\s*$",
        re.MULTILINE,
    ),
}
_ITC2007_VALIDATOR_SUMMARY = re.compile(
    r"^\s*Summary:\s*(?:Violations\s*=\s*(\d+)\s*,\s*)?Total Cost\s*=\s*(\d+)\s*$",
    re.MULTILINE,
)


def parse_itc2007_validator_output(stdout: str) -> ITC2007Validation:
    """Parse and cross-check the official validator's stdout summary."""

    values: dict[str, int] = {}
    for field_name, pattern in _ITC2007_VALIDATOR_FIELDS.items():
        matches = pattern.findall(stdout)
        if len(matches) != 1:
            raise ValueError(
                f"ITC-2007 validator output must contain exactly one {field_name} field; "
                f"found {len(matches)}"
            )
        values[field_name] = int(matches[0])

    summaries = _ITC2007_VALIDATOR_SUMMARY.findall(stdout)
    if len(summaries) != 1:
        raise ValueError(
            "ITC-2007 validator output must contain exactly one Summary line; "
            f"found {len(summaries)}"
        )
    summary_violations_raw, summary_cost_raw = summaries[0]
    summary_cost = int(summary_cost_raw)
    result = ITC2007Validation(
        **values,
        total_cost=summary_cost,
        stdout=stdout,
    )
    summary_violations = int(summary_violations_raw) if summary_violations_raw else 0
    if result.hard_violations != summary_violations:
        raise ValueError(
            "ITC-2007 validator hard-violation summary mismatch: "
            f"components={result.hard_violations}, summary={summary_violations}"
        )
    component_cost = (
        result.room_capacity
        + result.minimum_working_days
        + result.curriculum_compactness
        + result.room_stability
    )
    if component_cost != summary_cost:
        raise ValueError(
            "ITC-2007 validator soft-cost summary mismatch: "
            f"components={component_cost}, summary={summary_cost}"
        )
    return result


def run_itc2007_validator(
    validator_command: str | Path | Sequence[str | Path],
    instance_path: str | Path,
    solution_path: str | Path,
    *,
    timeout_seconds: float = 30.0,
) -> ITC2007Validation:
    """Run the official C++ validator without a shell and return checked metrics.

    ``validator_command`` may be the validator executable path or an argument
    sequence such as ``["docker", "run", ...]``. The instance and solution
    paths are appended in the order required by the official validator.
    """

    if isinstance(validator_command, (str, Path)):
        command = [str(validator_command)]
    else:
        command = [str(part) for part in validator_command]
    if not command:
        raise ValueError("validator_command must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    instance = Path(instance_path)
    solution = Path(solution_path)
    if not instance.is_file():
        raise FileNotFoundError(f"ITC-2007 instance does not exist: {instance}")
    if not solution.is_file():
        raise FileNotFoundError(f"ITC-2007 solution does not exist: {solution}")

    try:
        completed = subprocess.run(
            [*command, str(instance), str(solution)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        raise ITC2007ValidatorError(
            f"ITC-2007 validator timed out after {timeout_seconds:g} seconds"
        ) from exc
    except OSError as exc:
        raise ITC2007ValidatorError(
            f"Could not execute ITC-2007 validator command {command!r}: {exc}"
        ) from exc

    if completed.returncode != 0:
        diagnostic = (completed.stderr.strip() or completed.stdout.strip() or "no output")
        if len(diagnostic) > 2000:
            diagnostic = diagnostic[-2000:]
        raise ITC2007ValidatorError(
            f"ITC-2007 validator exited with exit code {completed.returncode}: {diagnostic}"
        )
    try:
        result = parse_itc2007_validator_output(completed.stdout)
    except ValueError as exc:
        raise ITC2007ValidatorError(
            f"ITC-2007 validator returned an unparseable or inconsistent report: {exc}"
        ) from exc
    return replace(
        result,
        returncode=int(completed.returncode),
        stderr=completed.stderr,
    )
