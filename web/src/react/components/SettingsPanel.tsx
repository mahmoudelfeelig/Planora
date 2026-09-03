import type { ChangeEvent } from "react";
import type { SolverSettings } from "../solver_settings";

type Props = {
  settings: SolverSettings;
  overridesEnabled: boolean;
  onChange(next: SolverSettings): void;
  onUseModeDefaults(): void;
};

function patchSettings(
  settings: SolverSettings,
  onChange: (next: SolverSettings) => void,
  patch: Partial<SolverSettings>,
) {
  onChange({ ...settings, ...patch });
}

export function SettingsPanel({ settings, overridesEnabled, onChange, onUseModeDefaults }: Props) {
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
    <section className="panel settings-panel advanced-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Specialist workspace</span>
          <h1>Advanced</h1>
          <p className="section-copy">
            Everyday scheduling uses Fast, Balanced, or Maximum quality. Only change these controls for research, verification, or a measured institutional need.
          </p>
        </div>
      </div>
      <div className="settings-notes advanced-notes">
        <div className="info-card">
          <strong>{overridesEnabled ? "Specialist overrides active" : "Mode defaults active"}</strong>
          <p>
            {overridesEnabled
              ? "These values override the server-owned mode for the next solve or improvement."
              : "Fast, Balanced, or Maximum quality is currently controlled by the shared backend."}
          </p>
          {overridesEnabled ? <button type="button" onClick={onUseModeDefaults}>Use mode defaults</button> : null}
        </div>
      </div>
      <details className="advanced-section">
        <summary>Engine and room strategy</summary>
        <div className="settings-grid">
        <label>
          Room mode
          <select value={settings.roomMode} onChange={onSelect("roomMode")}>
            <option value="greedy">Fast greedy</option>
            <option value="partitioned">Adaptive week partitions</option>
            <option value="cp_rooms">CP rooms</option>
            <option value="decomposed">Certificate decomposition</option>
          </select>
        </label>
        <label>
          Profile
          <select value={settings.profile} onChange={onSelect("profile")}>
            <option value="university_fast">University fast</option>
            <option value="balanced">Balanced</option>
            <option value="quality_first">Quality first</option>
            <option value="fairness_first">Fairness first</option>
            <option value="research_adaptive">Proof-guided adaptive LNS</option>
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
      </details>
      <details className="advanced-section">
        <summary>Improvement budget and progress</summary>
        <div className="settings-grid">
          <label>Improve iterations<input type="number" min={1} max={200000} value={settings.improveIterations} onChange={onNumber("improveIterations")} /></label>
          <label>Improve max seconds<input type="number" min={1} max={3600} value={settings.improveSeconds} onChange={onNumber("improveSeconds")} /></label>
          <label>Progress cadence<input type="number" min={1} max={10000} value={settings.progressEvery} onChange={onNumber("progressEvery")} /></label>
        </div>
      </details>
      <div className="settings-notes advanced-notes">
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
