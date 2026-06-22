import type { ChangeEvent } from "react";
import type { Dict, Instance, Schedule } from "../types";

type Props = {
  instance: Instance | null;
  schedule: Schedule;
  selectedWeek: number;
  targets: Dict[];
  heldActivityId: string;
  selectedActivityId: string;
  canEdit: boolean;
  onWeekChange(week: number): void;
  onSelectActivity(id: string): void;
  onHold(): void;
  onRelease(): void;
  onMoveTarget(day: string, slot: number): void;
};

function entityName(collection: Dict<Dict>, id: unknown, fallback: string): string {
  const row = collection[String(id)] || {};
  return String(row.name || row.code || fallback);
}

export function ScheduleBoard({
  instance,
  schedule,
  selectedWeek,
  targets,
  heldActivityId,
  selectedActivityId,
  canEdit,
  onWeekChange,
  onSelectActivity,
  onHold,
  onRelease,
  onMoveTarget,
}: Props) {
  const activityOptions = Object.entries(schedule).map(([id, row]: [string, Dict]) => {
    const course = instance ? entityName(instance.courses, row.course_id, `Course ${row.course_id}`) : `A${id}`;
    return { id, label: `A${id} ${course} W${row.week} ${row.day} S${Number(row.slot) + 1}` };
  });

  if (!instance) {
    return (
      <section className="panel empty-workspace">
        <img src="/app-icon.png" alt="" />
        <h2>Load a scenario to start</h2>
        <p>Use the planner controls above to load a preset or import a timetable, then solve and repair it.</p>
      </section>
    );
  }

  const weeks = instance.weeks.length ? instance.weeks : [1];
  const activeWeek = weeks.includes(selectedWeek) ? selectedWeek : Number(weeks[0]);
  const targetFor = (day: string, slot: number) =>
    targets.find((target: Dict) => String(target.day) === day && Number(target.slot) === slot);
  const changeWeek = (event: ChangeEvent<HTMLSelectElement>) => onWeekChange(Number(event.target.value));
  const changeActivity = (event: ChangeEvent<HTMLSelectElement>) => onSelectActivity(event.target.value);

  return (
    <section className="panel schedule-panel">
      <div className="panel-heading">
        <div>
          <h2>Manual Repair Board</h2>
          <p className="section-copy">
            {canEdit
              ? "Select an activity, hold it, then move it to a highlighted target. Green cells are viable. The badge shows the soft-penalty delta for that move."
              : "This is a permission-filtered read-only schedule view for your current organization and role."}
          </p>
        </div>
      </div>

      <div className="board-toolbar">
        <label>
          Week
          <select value={activeWeek} onChange={changeWeek}>
            {weeks.map((week) => (
              <option key={week} value={week}>
                Week {week}
              </option>
            ))}
          </select>
        </label>
        <label>
          Activity
          <select value={selectedActivityId} onChange={changeActivity} disabled={!canEdit}>
            <option value="">Select activity</option>
            {activityOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={!canEdit || !selectedActivityId} onClick={onHold}>
          Hold selected
        </button>
        <button type="button" disabled={!canEdit || !heldActivityId} onClick={onRelease}>
          Release hold
        </button>
      </div>

      <div className="hold-status">
        {heldActivityId
          ? `Holding A${heldActivityId}. Click a green target cell to execute the move.`
          : canEdit
            ? "Nothing is currently held. Select an activity and hold it to preview move deltas."
            : "Read-only mode. Ask a university admin for repair permissions if you need to edit this schedule."}
      </div>

      <div className="schedule-scroll">
        <table>
          <thead>
            <tr>
              <th>Day</th>
              {Array.from({ length: instance.slots_per_day }, (_, index) => (
                <th key={index}>Slot {index + 1}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {instance.days.map((day) => (
              <tr key={day}>
                <th>{day}</th>
                {Array.from({ length: instance.slots_per_day }, (_, slot) => {
                  const target = targetFor(String(day), slot);
                  const events = Object.entries(schedule).filter(
                    ([, row]: [string, Dict]) => Number(row.week) === activeWeek && String(row.day) === day && Number(row.slot) === slot,
                  );

                  return (
                    <td
                      key={`${day}-${slot}`}
                      className={target ? `move-target ${target.ok ? "viable" : "blocked"}` : ""}
                      onClick={() => canEdit && heldActivityId && target?.ok && onMoveTarget(String(day), slot)}
                    >
                      {target ? (
                        <span className={`delta-badge ${Number(target.delta || 0) <= 0 ? "better" : "worse"}`}>
                          {target.ok
                            ? `${Number(target.delta) >= 0 ? "+" : ""}${target.delta}`
                            : `blocked ${target.hard_conflict_count}`}
                        </span>
                      ) : null}
                      {events.map(([id, row]: [string, Dict]) => (
                        <div
                          key={id}
                          className={`event ${String(row.kind || "").toLowerCase()} ${String(id) === heldActivityId ? "held" : ""}`}
                        >
                          <strong>{entityName(instance.courses, row.course_id, `Course ${row.course_id}`)}</strong>
                          <span>
                            {String(row.kind || "")} · {entityName(instance.staff, row.staff_id, `Staff ${row.staff_id}`)}
                          </span>
                          <span>{entityName(instance.rooms, row.room_id, `Room ${row.room_id}`)}</span>
                        </div>
                      ))}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
