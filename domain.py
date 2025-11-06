from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple

Day = str          # e.g. "SAT", "MON", ...
SlotIndex = int    # 0..4
WeekIndex = int    # 1..12


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
    preferred_free_days: int = 2  # target free days per week for the group


@dataclass
class Course:
    id: int
    code: str
    name: str
    structure_type: str          # "LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB", "LAB_ONLY"
    lecture_count: int           # 12, 18, 24
    tutorial_count: int          # 0, 12, 18, 24
    lab_weeks: int               # 0 or 12
    lab_duration: int            # 1 or 2 consecutive slots
    share_lecture_group_ids: List[int] = field(default_factory=list)


@dataclass
class Staff:
    id: int
    name: str
    is_professor: bool
    is_block_professor: bool
    available_days: Set[Day]
    max_slots_per_day: Optional[int]
    max_slots_per_week: Optional[int]
    skilled_course_ids: Set[int]
    # for block-only profs, these are usually the only days they teach
    block_allowed_days: Set[Day] = field(default_factory=set)


@dataclass
class Room:
    id: int
    name: str
    room_type: str               # "LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"
    capacity: int
    specialization_tags: Set[str] = field(default_factory=set)
    # if empty, assume available all slots; otherwise explicit list
    available_day_slots: Set[Tuple[Day, SlotIndex]] = field(default_factory=set)


@dataclass
class Activity:
    """
    One concrete teaching event to be placed.
    Examples:
      - 1-slot weekly lecture for a course and group(s)
      - 1-slot tutorial per group
      - 1- or 2-slot lab
      - 3-slot block lecture for a block professor on selected weeks
    """
    id: int
    course_id: int
    group_ids: List[int]
    kind: str                    # "LEC", "TUT", "LAB"
    duration_slots: int          # 1, 2, or 3 if block lectures
    week: WeekIndex
    staff_candidates: List[int]
    requires_specialization: Optional[str] = None
    # pattern_id is kept for possible later refinements, not used in solver now
    pattern_id: Optional[int] = None


@dataclass
class Instance:
    days: List[Day]                         # ["SAT", "MON", "TUE", "WED", "THU", "FRI"]
    slots_per_day: int                      # 5
    weeks: List[WeekIndex]                  # [1..12]

    programs: Dict[int, Program]
    groups: Dict[int, Group]
    courses: Dict[int, Course]
    staff: Dict[int, Staff]
    rooms: Dict[int, Room]
    activities: Dict[int, Activity]
