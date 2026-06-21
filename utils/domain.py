from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional, Any


@dataclass
class Program:
    id: int
    name: str
    course_ids: List[int]
    group_ids: List[int]


@dataclass
class Group:
    id: int
    name: str
    program_id: int
    size: int
    course_ids: List[int]
    preferred_free_days: int = 2


@dataclass
class Course:
    id: int
    code: str
    name: str
    structure_type: str            # "LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB", "LAB_ONLY"
    lecture_count: int             # total over all weeks (12/18/24)
    tutorial_count: int            # 0 or 12/18/24
    lab_weeks: int                 # number of lab sessions over semester (0/12/18/24 in custom mode)
    lab_duration: int              # 1 or 2 consecutive slots
    share_lecture_group_ids: List[int] = field(default_factory=list)

    # exactly one professor and one TA per course
    prof_id: int | None = None
    ta_id: int | None = None


@dataclass
class StaffMember:
    id: int
    name: str
    is_prof: bool
    available_days: Set[str]
    max_slots_per_day: int | None
    max_slots_per_week: int | None
    can_teach_courses: Set[int] = field(default_factory=set)
    prefers_block: bool = False
    blocks_only: bool = False
    # None means all instance weeks are allowed.
    available_weeks: Optional[Set[int]] = None


@dataclass
class Room:
    id: int
    name: str
    capacity: int
    room_type: str                 # "LECTURE", "TUTORIAL", "SPECIALIZED_LAB", "COMPUTER_LAB"
    campus: str = "MAIN"
    building: str = ""
    floor: str = ""
    features: Set[str] = field(default_factory=set)
    specialization_tags: Set[str] = field(default_factory=set)
    # Optional availability; when None, the room is assumed available for all (day, slot) pairs.
    availability: Optional[Set[Tuple[str, int]]] = None


@dataclass
class GenericResource:
    id: int
    name: str
    resource_type: str
    capacity: int = 1
    tags: Set[str] = field(default_factory=set)
    availability: Optional[Set[Tuple[str, int]]] = None


@dataclass
class Activity:
    id: int
    course_id: int
    week: int
    kind: str                      # "LEC", "TUT", "LAB"
    duration: int                  # number of slots (1, 2, or 3)
    group_ids: List[int]
    prof_id: int
    ta_id: int
    requires_specialization: str | None = None
    resource_ids: List[int] = field(default_factory=list)


@dataclass
class Instance:
    days: List[str]
    slots_per_day: int
    weeks: List[int]

    programs: Dict[int, Program]
    groups: Dict[int, Group]
    courses: Dict[int, Course]
    staff: Dict[int, StaffMember]
    rooms: Dict[int, Room]
    activities: Dict[int, Activity]
    generic_resources: Dict[int, GenericResource] = field(default_factory=dict)

    # Optional: activity locks for partial re-solving. Keys are activity ids; values may contain
    # any of: "day" (str), "slot" (int), "room_id" (int).
    locked_activities: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # Optional: global soft constraint weights for CP objective (when used).
    soft_weights: Dict[str, int] = field(default_factory=dict)

    # Optional: preferred solve profile for downstream services/UI.
    objective_profile: str = "balanced"

    # Optional: hard-constraint toggles consumed by solver/validators.
    hard_constraints: Dict[str, bool] = field(default_factory=dict)

    # Optional: travel buffers in slots (`same_building`, `cross_building`, `cross_campus`).
    travel_time_rules: Dict[str, int] = field(default_factory=dict)

    # Optional: building/campus closure rules.
    room_closures: List[Dict[str, Any]] = field(default_factory=list)

    # Optional: calendar blackout/holiday/exam rules.
    calendar_rules: Dict[str, Any] = field(default_factory=dict)

    # Optional: precedence constraints between activities.
    precedence_rules: List[Dict[str, Any]] = field(default_factory=list)

    # Optional: target thresholds used for quality/SLA reporting.
    sla_targets: Dict[str, Any] = field(default_factory=dict)

    # Optional: arbitrary named term blocks across the week sequence.
    term_blocks: List[Dict[str, Any]] = field(default_factory=list)
