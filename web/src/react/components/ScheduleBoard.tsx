import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import {
  ArrowClockwise,
  CalendarBlank,
  CaretDown,
  CaretRight,
  Check,
  CheckCircle,
  Clock,
  MagnifyingGlass,
  MagicWand,
  PaperPlaneTilt,
  X,
} from "@phosphor-icons/react";
import type { Dict, Instance, Schedule } from "../types";

type Props = {
  instance: Instance | null;
  schedule: Schedule;
  selectedWeek: number;
  targets: Dict[];
  heldActivityId: string;
  selectedActivityId: string;
  conflicts: string[];
  score: Dict;
  runModeLabel: string;
  busy: boolean;
  canEdit: boolean;
  onWeekChange(week: number): void;
  onSelectActivity(id: string): void;
  onHold(id?: string): void;
  onRelease(): void;
  onMoveTarget(day: string, slot: number): void;
  onOpenData(): void;
  onSolve(): void;
  onImprove(): void;
  onValidate(): void;
  onPublish(): void;
};

function entity(collection: Dict<Dict>, id: unknown): Dict {
  return collection[String(id)] || {};
}

function entityName(collection: Dict<Dict>, id: unknown, fallback: string): string {
  const row = entity(collection, id);
  return String(row.name || row.code || fallback);
}

function eventTone(id: string): number {
  return [...id].reduce((value, character) => value + character.charCodeAt(0), 0) % 6;
}

function ResourceSection({ title, rows, selected, onSelect }: { title: string; rows: Array<{ id: string; label: string }>; selected?: string; onSelect?(id: string): void }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="resource-section">
      <button type="button" className="resource-heading" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {open ? <CaretDown aria-hidden="true" weight="bold" /> : <CaretRight aria-hidden="true" weight="bold" />}<strong>{title}</strong><small>{rows.length}</small>
      </button>
      {open ? <div className="resource-list">{rows.slice(0, 14).map((row) => (
        <button type="button" className={selected === row.id ? "active" : ""} key={row.id} onClick={() => onSelect?.(row.id)}>{row.label}</button>
      ))}</div> : null}
    </section>
  );
}

export function ScheduleBoard({
  instance,
  schedule,
  selectedWeek,
  targets,
  heldActivityId,
  selectedActivityId,
  conflicts,
  score,
  runModeLabel,
  busy,
  canEdit,
  onWeekChange,
  onSelectActivity,
  onHold,
  onRelease,
  onMoveTarget,
  onOpenData,
  onSolve,
  onImprove,
  onValidate,
  onPublish,
}: Props) {
  const [resourceQuery, setResourceQuery] = useState("");
  const scheduleIndex = useMemo(() => {
    const index = new Map<string, Array<[string, Dict]>>();
    Object.entries(schedule).forEach(([id, row]: [string, Dict]) => {
      const key = `${Number(row.week)}:${String(row.day)}:${Number(row.slot)}`;
      index.set(key, [...(index.get(key) || []), [id, row]]);
    });
    return index;
  }, [schedule]);

  if (!instance) {
    return (
      <section className="empty-blueprint">
        <img src="/app-icon.png" alt="" />
        <span className="eyebrow">New academic plan</span>
        <h1>Bring in timetable data to begin</h1>
        <p>Open the Spring 2023 university example or import your own courses, rooms, staff, and groups.</p>
        <button type="button" onClick={onOpenData}>Choose timetable data</button>
      </section>
    );
  }

  const weeks = instance.weeks.length ? instance.weeks : [1];
  const activeWeek = weeks.includes(selectedWeek) ? selectedWeek : Number(weeks[0]);
  const targetFor = (day: string, slot: number) => targets.find((target) => String(target.day) === day && Number(target.slot) === slot);
  const selectedRow = selectedActivityId ? (schedule[selectedActivityId] || {}) : {};
  const selectedActivity = selectedActivityId ? (instance.activities[selectedActivityId] || {}) : {};
  const filter = (label: string) => label.toLowerCase().includes(resourceQuery.trim().toLowerCase());
  const resourceRows = (collection: Dict<Dict>) => Object.entries(collection).map(([id, row]) => ({ id, label: String(row.name || row.code || id) })).filter((row) => filter(row.label));

  const coveredCells = new Set<string>();
  const slotRows = Array.from({ length: instance.slots_per_day }, (_, slot) => (
    <tr key={slot}>
      <th scope="row">{String(slot + 8).padStart(2, "0")}:00</th>
      {instance.days.map((rawDay) => {
        const day = String(rawDay);
        const cellKey = `${day}:${slot}`;
        if (coveredCells.has(cellKey)) return null;
        const target = targetFor(day, slot);
        const events = scheduleIndex.get(`${activeWeek}:${day}:${slot}`) || [];
        const activity = events.length === 1 ? (instance.activities[events[0][0]] || {}) : {};
        const requestedSpan = events.length === 1 ? Math.max(1, Number(events[0][1].duration ?? activity.duration ?? 1)) : 1;
        let span = Math.min(requestedSpan, instance.slots_per_day - slot);
        for (let offset = 1; offset < span; offset += 1) {
          if (targets.some((row) => String(row.day) === day && Number(row.slot) === slot + offset) || scheduleIndex.has(`${activeWeek}:${day}:${slot + offset}`)) {
            span = 1;
            break;
          }
        }
        for (let offset = 1; offset < span; offset += 1) coveredCells.add(`${day}:${slot + offset}`);
        return (
          <td
            key={cellKey}
            rowSpan={span}
            className={`${target ? `move-target ${target.ok ? "viable" : "blocked"}` : ""} ${span > 1 ? "multi-slot" : ""}`}
            onDragOver={(event) => { if (canEdit && heldActivityId && target?.ok) event.preventDefault(); }}
            onDrop={(event) => { event.preventDefault(); if (canEdit && heldActivityId && target?.ok) onMoveTarget(day, slot); }}
          >
            {target?.ok && canEdit && heldActivityId ? (
              <button
                type="button"
                className={`delta-badge move-target-button ${Number(target.delta || 0) <= 0 ? "better" : "worse"}`}
                aria-label={`Move held class to ${day}, slot ${slot + 1}`}
                onClick={() => onMoveTarget(day, slot)}
              >
                {`${Number(target.delta) >= 0 ? "+" : ""}${target.delta}`}
              </button>
            ) : target ? (
              <span className={`delta-badge ${Number(target.delta || 0) <= 0 ? "better" : "worse"}`}>blocked</span>
            ) : null}
            {events.map(([id, row]) => (
              <button
                type="button"
                key={id}
                className={`event event-tone-${eventTone(id)} ${String(row.kind || "").toLowerCase()} ${id === heldActivityId ? "held" : ""} ${id === selectedActivityId ? "selected" : ""}`}
                draggable={canEdit}
                onClick={(event) => { event.stopPropagation(); onSelectActivity(id); }}
                onDoubleClick={() => canEdit && onHold(id)}
                onDragStart={(event) => { event.dataTransfer.setData("text/plain", id); onSelectActivity(id); onHold(id); }}
              >
                <strong>{entityName(instance.courses, row.course_id, `Course ${row.course_id}`)}</strong>
                <span>{String(row.kind || "Class")} · {entityName(instance.staff, row.staff_id, `Staff ${row.staff_id}`)}</span>
                <small>{entityName(instance.rooms, row.room_id, `Room ${row.room_id}`)}</small>
              </button>
            ))}
          </td>
        );
      })}
    </tr>
  ));

  return (
    <section className="blueprint-workspace">
      <header className="blueprint-toolbar">
        <div className="blueprint-context"><span className="blueprint-breadcrumb">Planora University / Academic planning</span><strong>Draft timetable</strong><small>Week {activeWeek} · {runModeLabel}</small></div>
        <div className="blueprint-actions">
          <button type="button" className="secondary-button" disabled={busy} onClick={onValidate}><Check aria-hidden="true" weight="bold" />Validate</button>
          <button type="button" className="secondary-button" disabled={busy || !Object.keys(schedule).length} onClick={onImprove}><MagicWand aria-hidden="true" weight="bold" />Improve</button>
          <button type="button" disabled={busy || !Object.keys(schedule).length || conflicts.length > 0} onClick={onPublish}><PaperPlaneTilt aria-hidden="true" weight="fill" />Publish</button>
        </div>
      </header>

      <div className="blueprint-grid">
        <aside className="resource-browser">
          <label className="resource-search">Find a resource<span className="resource-input"><MagnifyingGlass aria-hidden="true" /><input value={resourceQuery} onChange={(event) => setResourceQuery(event.target.value)} placeholder="Course, group, room…" /></span></label>
          <ResourceSection title="Programs" rows={resourceRows(instance.programs || {})} />
          <ResourceSection title="Groups" rows={resourceRows(instance.groups)} />
          <ResourceSection title="Courses" rows={resourceRows(instance.courses)} />
          <ResourceSection title="Staff" rows={resourceRows(instance.staff)} />
          <ResourceSection title="Rooms" rows={resourceRows(instance.rooms)} />
        </aside>

        <main className="timetable-canvas">
          <div className="schedule-toolbar">
            <label className="week-select"><span><CalendarBlank aria-hidden="true" />Week</span><select value={activeWeek} onChange={(event: ChangeEvent<HTMLSelectElement>) => onWeekChange(Number(event.target.value))}>{weeks.map((week) => <option key={week} value={week}>Week {week}</option>)}</select></label>
            <div className="schedule-state"><CheckCircle aria-hidden="true" weight="fill" /><span><strong>{Object.keys(schedule).length ? `${Object.keys(schedule).length} activities placed` : "Ready to build a draft"}</strong><small>{conflicts.length} hard conflicts · score {String(score.soft_penalty ?? 0)}</small></span></div>
            <button type="button" disabled={busy} onClick={onSolve}><ArrowClockwise aria-hidden="true" weight="bold" />{Object.keys(schedule).length ? "Rebuild draft" : "Build schedule"}</button>
          </div>
          <div className="schedule-scroll">
            <table>
              <thead><tr><th>Time</th>{instance.days.map((day) => <th key={String(day)}>{String(day)}</th>)}</tr></thead>
              <tbody>{slotRows}</tbody>
            </table>
          </div>
          <div className="run-strip"><Clock aria-hidden="true" /><span>Current draft</span><strong>Score {String(score.soft_penalty ?? 0)}</strong><span>{conflicts.length} hard conflicts</span><button type="button" className="quiet-button" onClick={onValidate}>View run details <CaretRight aria-hidden="true" /></button></div>
        </main>

        <aside className="activity-inspector">
          {selectedActivityId ? (
            <>
              <header><button type="button" className="inspector-close" aria-label="Close activity details" onClick={() => onSelectActivity("")}><X aria-hidden="true" /></button><span className="eyebrow">Selected class</span><h2>{entityName(instance.courses, selectedRow.course_id ?? selectedActivity.course_id, `Activity ${selectedActivityId}`)}</h2><p>{String(selectedRow.kind || selectedActivity.kind || "Class")} · Week {String(selectedRow.week || selectedActivity.week || activeWeek)}</p></header>
              <section><h3>Details</h3><dl><div><dt>Room</dt><dd>{entityName(instance.rooms, selectedRow.room_id, "Unassigned")}</dd></div><div><dt>Staff</dt><dd>{entityName(instance.staff, selectedRow.staff_id, "Unassigned")}</dd></div><div><dt>Time</dt><dd>{String(selectedRow.day || "Not placed")} · Slot {Number(selectedRow.slot ?? -1) + 1}</dd></div></dl></section>
              <section><h3>Conflicts</h3>{conflicts.length ? <p className="inspector-warning">{conflicts[0]}</p> : <p className="inspector-clear">No hard conflict is currently reported.</p>}</section>
              {canEdit ? <section><h3>Suggestions</h3><p>Preview safe alternatives and choose a lower-score move.</p><button type="button" onClick={() => heldActivityId ? onRelease() : onHold(selectedActivityId)}>{heldActivityId ? "Stop preview" : "Show suggestions"}</button></section> : null}
            </>
          ) : (
            <div className="inspector-empty"><img src="/app-icon.png" alt="" /><h2>Select a class</h2><p>Its room, teacher, conflicts, and explained suggestions will appear here.</p></div>
          )}
        </aside>
      </div>
    </section>
  );
}
