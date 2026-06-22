import type { Dict } from "../types";

export function ReviewPanel({ conflicts, score }: { conflicts: string[]; score: Dict }) {
  const drivers = Array.isArray(score.drivers) ? score.drivers as Dict[] : [];
  const suggestions = [
    ...conflicts.slice(0, 6).map((conflict) => {
      const text = conflict.toLowerCase();
      if (text.includes("room")) return `Room conflict: hold one affected activity, preview green target cells, then move it to a different room/time with the lowest delta. (${conflict})`;
      if (text.includes("staff") || text.includes("prof") || text.includes("ta")) return `Staff conflict: move one activity away from the overlapping slot, or assign an alternate eligible staff member before solving again. (${conflict})`;
      if (text.includes("group")) return `Group conflict: separate the overlapping activities for the same student group, prioritizing the one with more eligible rooms. (${conflict})`;
      return `Repair candidate: inspect this hard conflict, hold one involved activity, and move it to a viable target. (${conflict})`;
    }),
    ...drivers.slice(0, 4).map((driver) => {
      const label = String(driver.label || driver.term || "penalty").toLowerCase();
      if (label.includes("thin")) return "Quality focus: run Improve with the thin-day focus to consolidate sparse teaching days.";
      if (label.includes("same") || label.includes("kind")) return "Quality focus: run Improve with same-kind week focus to align recurring activities more consistently.";
      if (label.includes("room")) return "Quality focus: prioritize room consistency or enable the repeated weekly pattern when the instance supports it.";
      return `Quality focus: reduce ${String(driver.label || driver.term || "the top penalty driver")} using Improve or manual low-delta moves.`;
    }),
  ];
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Conflicts & Diagnostics</h2>
            <p className="section-copy">
              Hard conflicts are issues the schedule must eliminate. Diagnostics below explain the biggest remaining soft-penalty sources after scoring.
            </p>
          </div>
        </div>
        <ol className="conflict-list">
          {conflicts.length ? conflicts.map((conflict, index) => <li key={index}>{conflict}</li>) : <li>None</li>}
        </ol>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Repair Workflow</h2>
            <p className="section-copy">
              These are practical next actions derived from the current conflict list and score drivers.
            </p>
          </div>
        </div>
        <ol className="conflict-list">
          {suggestions.length ? suggestions.map((suggestion, index) => <li key={index}>{suggestion}</li>) : <li>Load, solve, or score a timetable to see repair suggestions.</li>}
        </ol>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Penalty Drivers</h2>
            <p className="section-copy">
              These terms show where the current score comes from, so you can decide whether to focus on spread, room stability, thin days, or another quality dimension.
            </p>
          </div>
        </div>
        <div className="driver-list">
          {drivers.length ? drivers.map((driver, index) => (
            <div key={index} className="driver-row">
              <span>{String(driver.label || driver.term || "Penalty")}</span>
              <strong>{String(driver.penalty ?? driver.value ?? "")}</strong>
            </div>
          )) : "Score the schedule to see drivers."}
        </div>
      </section>
    </div>
  );
}
