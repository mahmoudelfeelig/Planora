import { useMemo, useState } from "react";
import type { Dict, Instance } from "../types";
import type { UiRunMode, UiScenario } from "../planner_api";

type Props = {
  instance: Instance | null;
  scenarios: UiScenario[];
  modes: UiRunMode[];
  runMode: string;
  busy: boolean;
  onRunModeChange(mode: string): void;
  onLoadScenario(scenario: UiScenario): void;
  onImportCsv(filename: string, content: string, fieldMap: Dict<string>): Promise<void>;
};

function count(instance: Instance | null, key: keyof Instance): number {
  if (!instance) return 0;
  const value = instance[key];
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return 0;
}

export function OperationsPanel({
  instance,
  scenarios,
  modes,
  runMode,
  busy,
  onRunModeChange,
  onLoadScenario,
  onImportCsv,
}: Props) {
  const [showImport, setShowImport] = useState(false);
  const [csvFilename, setCsvFilename] = useState("schedule.csv");
  const [csvContent, setCsvContent] = useState("");
  const [fieldMapText, setFieldMapText] = useState("week=week, day=day, slot=slot, course=course, group=group, room=room, kind=kind, lecturer=lecturer, ta=ta");
  const fieldMap = useMemo(() => {
    const out: Dict<string> = {};
    fieldMapText.split(",").forEach((part) => {
      const [logical, column] = part.split("=").map((value) => value.trim());
      if (logical && column) out[logical] = column;
    });
    return out;
  }, [fieldMapText]);

  return (
    <div className="data-page stack">
      <section className="panel data-hero">
        <div>
          <span className="eyebrow">Data workspace</span>
          <h1>Build from familiar university data</h1>
          <p>Start with a guided example or bring the timetable you already maintain. Technical generators remain available in Advanced.</p>
        </div>
        {instance ? (
          <div className="data-summary" aria-label="Loaded timetable summary">
            <span><strong>{count(instance, "activities")}</strong> activities</span>
            <span><strong>{count(instance, "courses")}</strong> courses</span>
            <span><strong>{count(instance, "rooms")}</strong> rooms</span>
            <span><strong>{count(instance, "staff")}</strong> staff</span>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><h2>Choose timetable data</h2><p className="section-copy">The Spring 2023 option is the university-scale working scenario.</p></div>
        </div>
        <div className="scenario-card-grid">
          {scenarios.map((scenario) => (
            <article className="scenario-card" key={scenario.id}>
              <span className="scenario-badge">{scenario.badge || "Scenario"}</span>
              <h3>{scenario.label}</h3>
              <p>{scenario.description}</p>
              {scenario.id === "import"
                ? <button type="button" className="secondary-button" onClick={() => setShowImport((open) => !open)}>{showImport ? "Close import" : "Import timetable"}</button>
                : <button type="button" disabled={busy} onClick={() => onLoadScenario(scenario)}>Open scenario</button>}
            </article>
          ))}
        </div>

        {showImport ? (
          <form className="import-sheet" onSubmit={(event) => {
            event.preventDefault();
            void onImportCsv(csvFilename, csvContent, fieldMap);
          }}>
            <div className="import-sheet-heading"><strong>Import a timetable CSV</strong><span>Required: week, day, slot, and course.</span></div>
            <label>File name<input value={csvFilename} onChange={(event) => setCsvFilename(event.target.value)} /></label>
            <label>Column mapping<input value={fieldMapText} onChange={(event) => setFieldMapText(event.target.value)} /></label>
            <label className="import-content">CSV content<textarea rows={9} value={csvContent} onChange={(event) => setCsvContent(event.target.value)} placeholder="week,day,slot,course,group,room&#10;1,MON,1,Algorithms,P1-G1,R101" /></label>
            <button type="submit" disabled={busy || !csvContent.trim()}>Import and review</button>
          </form>
        ) : null}
      </section>

      <section className="panel run-mode-section">
        <div className="panel-heading">
          <div><h2>Default planning approach</h2><p className="section-copy">Choose the result you want. Planora selects the underlying engine settings.</p></div>
        </div>
        <div className="run-mode-grid">
          {modes.map((mode) => (
            <label className={`run-mode-card ${runMode === mode.id ? "selected" : ""}`} key={mode.id}>
              <input type="radio" name="run-mode" value={mode.id} checked={runMode === mode.id} onChange={() => onRunModeChange(mode.id)} />
              <span>{mode.recommended ? "Recommended" : "Planning mode"}</span>
              <strong>{mode.label}</strong>
              <small>{mode.description}</small>
            </label>
          ))}
        </div>
      </section>
    </div>
  );
}

export function RunSummary({ score, conflicts }: { score: Dict; conflicts: string[] }) {
  return (
    <section className="panel metric-panel">
      <div className="panel-heading"><div><h2>Current draft</h2><p className="section-copy">Lower penalty is better; hard conflicts must reach zero before publishing.</p></div></div>
      <div className="metric-grid">
        <div><span>Soft penalty</span><strong>{String(score.soft_penalty ?? 0)}</strong></div>
        <div><span>Hard conflicts</span><strong>{String(score.hard_conflict_count ?? conflicts.length)}</strong></div>
        <div><span>Best bound</span><strong>{String(score.best_bound ?? "n/a")}</strong></div>
        <div><span>Gap</span><strong>{String(score.gap ?? "n/a")}</strong></div>
      </div>
    </section>
  );
}
