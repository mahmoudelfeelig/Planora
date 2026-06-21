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
  settings: SolverSettings;
  onChange(next: SolverSettings): void;
};

function patchSettings(
  settings: SolverSettings,
  onChange: (next: SolverSettings) => void,
  patch: Partial<SolverSettings>,
) {
  onChange({ ...settings, ...patch });
}

export function SettingsPanel({ settings, onChange }: Props) {
  const onSelect =
    (key: "roomMode" | "profile") =>
    (event: ChangeEvent<HTMLSelectElement>) =>
      patchSettings(settings, onChange, { [key]: event.target.value } as Partial<SolverSettings>);
  const onNumber =
    (key: "timeLimitSeconds" | "workers" | "improveIterations" | "improveSeconds" | "progressEvery") =>
    (event: ChangeEvent<HTMLInputElement>) =>
      patchSettings(settings, onChange, { [key]: Number(event.target.value || 1) } as Partial<SolverSettings>);
  const onToggle =
    (key: "useObjective" | "forceRepeatWeeklyPattern") =>
    (event: ChangeEvent<HTMLInputElement>) =>
      patchSettings(settings, onChange, { [key]: event.target.checked } as Partial<SolverSettings>);

  return (
    <section className="panel settings-panel">
      <div className="panel-heading">
        <div>
          <h2>Solver Settings</h2>
          <p className="section-copy">
            These settings drive both Solve and Improve actions. Keep workers moderate unless you have measured that more parallel search actually helps on your instances.
          </p>
        </div>
      </div>

      <div className="settings-grid">
        <label>
          Room mode
          <select value={settings.roomMode} onChange={onSelect("roomMode")}>
            <option value="greedy">Fast greedy</option>
            <option value="cp_rooms">CP rooms</option>
          </select>
        </label>
        <label>
          Profile
          <select value={settings.profile} onChange={onSelect("profile")}>
            <option value="university_fast">University fast</option>
            <option value="balanced">Balanced</option>
            <option value="quality_first">Quality first</option>
          </select>
        </label>
        <label>
          Time limit (seconds)
          <input
            type="number"
            min={1}
            max={3600}
            value={settings.timeLimitSeconds}
            onChange={onNumber("timeLimitSeconds")}
          />
        </label>
        <label>
          Workers
          <input
            type="number"
            min={1}
            max={64}
            value={settings.workers}
            onChange={onNumber("workers")}
          />
        </label>
        <label>
          Improve iterations
          <input
            type="number"
            min={1}
            max={200000}
            value={settings.improveIterations}
            onChange={onNumber("improveIterations")}
          />
        </label>
        <label>
          Improve max seconds
          <input
            type="number"
            min={1}
            max={3600}
            value={settings.improveSeconds}
            onChange={onNumber("improveSeconds")}
          />
        </label>
        <label>
          Progress cadence
          <input
            type="number"
            min={1}
            max={10000}
            value={settings.progressEvery}
            onChange={onNumber("progressEvery")}
          />
        </label>
        <label className="toggle-field">
          <span>Use CP objective</span>
          <input
            type="checkbox"
            checked={settings.useObjective}
            onChange={onToggle("useObjective")}
          />
        </label>
        <label className="toggle-field">
          <span>Force same weekly pattern after week 1</span>
          <input
            type="checkbox"
            checked={settings.forceRepeatWeeklyPattern}
            onChange={onToggle("forceRepeatWeeklyPattern")}
          />
        </label>
      </div>

      <div className="settings-notes">
        <div className="info-card">
          <strong>Workers</strong>
          <p>
            Workers are CP-SAT search threads. They usually map to CPU concurrency, but more threads do not guarantee better bounds or faster first solutions.
          </p>
        </div>
        <div className="info-card">
          <strong>Repeat pattern</strong>
          <p>
            This hard constraint forces weeks after week 1 to reuse the same time and room pattern whenever the instance supports it. Small demos may become infeasible under this rule.
          </p>
        </div>
      </div>
    </section>
  );
}
import type { ChangeEvent } from "react";
