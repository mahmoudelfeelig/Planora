import type { Dict } from "../types";

export function ReviewPanel({ conflicts, score }: { conflicts: string[]; score: Dict }) {
  const drivers = Array.isArray(score.drivers) ? score.drivers as Dict[] : [];
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
