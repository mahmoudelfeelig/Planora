import type { ChangeEvent } from "react";
import type { Dict, Instance } from "../types";

type SolverSettings = {
  roomMode: string;
  profile: string;
  timeLimitSeconds: number;
  workers: number;
  useObjective: boolean;
  forceRepeatWeeklyPattern: boolean;
  improveIterations: number;
  improveSeconds: number;
  progressEvery: number;
};

type Props = {
  instance: Instance | null;
  presets: string[];
  busy: boolean;
  settings: SolverSettings;
  onLoadPreset(mode: string): void;
  onSolve(): void;
  onImprove(): void;
  onScore(): void;
  onStartImproveJob(): void;
};

function statValue(instance: Instance | null, key: keyof Instance): number {
  if (!instance) return 0;
  const value = instance[key];
  if (Array.isArray(value)) return value.length;
  if (typeof value === "object" && value) return Object.keys(value).length;
  return 0;
}

export function OperationsPanel({
  instance,
  presets,
  busy,
  settings,
  onLoadPreset,
  onSolve,
  onImprove,
  onScore,
  onStartImproveJob,
}: Props) {
  const loaded = Boolean(instance);
  const loadPreset = (event: ChangeEvent<HTMLSelectElement>) => {
    if (event.target.value) onLoadPreset(event.target.value);
  };

  return (
    <section className="panel operations-panel">
      <div className="panel-heading">
        <div>
          <h2>Run Planner</h2>
          <p className="section-copy">
            Load or import a scenario, build a feasible timetable, then repair or improve it. The actions below are grouped by intent so the flow is explicit.
          </p>
        </div>
      </div>

      <div className="operation-sections">
        <div className="action-card">
          <div className="action-card-head">
            <strong>1. Load scenario</strong>
            <span className="muted">Preset or imported timetable</span>
          </div>
          <label>
            Preset
            <select disabled={busy} onChange={loadPreset} defaultValue="">
              <option value="">Choose scenario</option>
              {presets.map((preset) => (
                <option key={preset} value={preset}>
                  {preset.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <div className="stat-strip">
            <span>Weeks: {statValue(instance, "weeks")}</span>
            <span>Activities: {statValue(instance, "activities")}</span>
            <span>Rooms: {statValue(instance, "rooms")}</span>
            <span>Staff: {statValue(instance, "staff")}</span>
          </div>
        </div>

        <div className="action-card">
          <div className="action-card-head">
            <strong>2. Build feasible schedule</strong>
            <span className="muted">
              {settings.roomMode} · {settings.profile} · {settings.timeLimitSeconds}s · {settings.workers} workers
            </span>
          </div>
          <p className="action-copy">
            <strong>Solve</strong> runs the full scheduler and tries to produce a hard-conflict-free timetable using the current settings.
          </p>
          <button type="button" disabled={!loaded || busy} onClick={onSolve}>
            Solve schedule
          </button>
        </div>

        <div className="action-card">
          <div className="action-card-head">
            <strong>3. Improve quality</strong>
            <span className="muted">
              {settings.improveIterations} LS iterations · {settings.improveSeconds}s
            </span>
          </div>
          <p className="action-copy">
            <strong>Improve now</strong> runs local search immediately in this session and replaces the current timetable when it finishes.
          </p>
          <p className="action-copy">
            <strong>Improve as background job</strong> starts the same search on the server and lets you keep navigating while it runs.
          </p>
          <div className="button-pair">
            <button type="button" disabled={!loaded || busy} onClick={onImprove}>
              Improve now
            </button>
            <button type="button" disabled={!loaded || busy} onClick={onStartImproveJob}>
              Improve as background job
            </button>
          </div>
        </div>

        <div className="action-card">
          <div className="action-card-head">
            <strong>4. Analyze current result</strong>
            <span className="muted">No placements change</span>
          </div>
          <p className="action-copy">
            <strong>Recalculate score</strong> recomputes soft penalty, hard conflicts, CP bound, and gap for the timetable currently in memory.
          </p>
          <button type="button" disabled={!loaded || busy} onClick={onScore}>
            Recalculate score
          </button>
        </div>
      </div>
    </section>
  );
}

export function RunSummary({ score, conflicts }: { score: Dict; conflicts: string[] }) {
  const bestBound = score.best_bound ?? "n/a";
  const gap = score.gap ?? "n/a";

  return (
    <section className="panel metric-panel">
      <div className="panel-heading">
        <div>
          <h2>Run Summary</h2>
          <p className="section-copy">
            This is the current evaluated state of the loaded timetable. Lower soft penalty is better; hard conflicts should stay at zero.
          </p>
        </div>
      </div>
      <div className="metric-grid">
        <div>
          <span>Soft penalty</span>
          <strong>{String(score.soft_penalty ?? 0)}</strong>
        </div>
        <div>
          <span>Hard conflicts</span>
          <strong>{String(score.hard_conflict_count ?? conflicts.length)}</strong>
        </div>
        <div>
          <span>Best bound</span>
          <strong>{String(bestBound)}</strong>
        </div>
        <div>
          <span>Gap</span>
          <strong>{String(gap)}</strong>
        </div>
      </div>
      <div className="inline-note">
        Best bound and gap are only available when the CP-SAT run produced bound information. Heuristic-only runs will show <strong>n/a</strong>.
      </div>
    </section>
  );
}
