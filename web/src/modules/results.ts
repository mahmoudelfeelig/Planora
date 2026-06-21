export type Dict<T = any> = Record<string, T>;

export type WebState = {
  instance: Dict | null;
  schedule: Dict<Dict>;
  meta: Dict;
  conflicts: string[];
  score: Dict;
};

export type ResultTargets = {
  resultSummary: HTMLDivElement;
  insights: HTMLDivElement;
  penaltyDrivers: HTMLDivElement;
  sideConflicts: HTMLOListElement;
  resultsConflicts: HTMLOListElement;
  rawDiagnostics: HTMLElement;
};

export function displayValue(value: unknown, fallback = "Unavailable"): string {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "number" && Number.isFinite(value)) return String(Math.round(value * 100) / 100);
  return String(value);
}

function latestAttempt(state: WebState): Dict {
  const attempts = (state.meta?.attempts || []) as Dict[];
  return attempts.length ? attempts[attempts.length - 1] : {};
}

export function buildResultRows(state: WebState, workerValue = ""): Array<[string, string]> {
  const inst = state.instance;
  const scheduleCount = Object.keys(state.schedule || {}).length;
  const attempt = latestAttempt(state);
  const rawStatus = state.meta?.final_raw_status ?? state.meta?.raw_status ?? attempt.raw_status ?? state.meta?.status;
  const elapsed = state.meta?.elapsed_seconds ?? attempt.elapsed_seconds;
  const bound =
    state.score?.best_bound ??
    state.meta?.best_bound ??
    state.meta?.objective_bound ??
    state.meta?.cp_bound ??
    state.meta?.quality?.best_bound;
  const gap =
    state.score?.gap ??
    state.meta?.gap ??
    state.meta?.objective_gap ??
    state.meta?.quality?.gap;
  return [
    ["Scheduled", `${scheduleCount}/${inst ? Object.keys(inst.activities || {}).length : 0}`],
    ["Soft penalty", displayValue(state.score.soft_penalty, "0")],
    ["Hard conflicts", displayValue(state.score.hard_conflict_count ?? state.conflicts.length, "0")],
    ["Solver status", displayValue(rawStatus, state.schedule && scheduleCount ? "Feasible" : "Not run")],
    ["Best bound", displayValue(bound)],
    ["Gap", displayValue(gap)],
    ["Elapsed", elapsed == null ? "Unavailable" : `${displayValue(elapsed)}s`],
    ["Workers", displayValue(attempt.workers ?? workerValue)],
  ];
}

export function renderKeyValueGrid(target: HTMLDivElement, rows: Array<[string, string]>): void {
  target.replaceChildren(...rows.map(([label, value]) => {
    const item = document.createElement("div");
    item.className = "result-item";
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("strong");
    labelNode.textContent = label;
    valueNode.textContent = value;
    item.append(labelNode, valueNode);
    return item;
  }));
}

export function renderInsightRows(target: HTMLDivElement, rows: Array<[string, string]>): void {
  target.replaceChildren(...rows.map(([label, value]) => {
    const row = document.createElement("div");
    row.className = "insight-row";
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("strong");
    labelNode.textContent = label;
    valueNode.textContent = value;
    row.append(labelNode, valueNode);
    return row;
  }));
}

export function penaltyDriverRows(score: Dict): Array<[string, string]> {
  const drivers = (score.drivers || []) as Dict[];
  if (drivers.length) {
    return drivers.slice(0, 8).map((driver) => [
      displayValue(driver.label ?? driver.name ?? driver.term ?? driver.reason ?? driver.kind, "Penalty driver"),
      displayValue(driver.penalty ?? driver.value ?? driver.score ?? driver.amount, "0"),
    ]);
  }
  const breakdown = score.breakdown || {};
  return Object.entries(breakdown)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 8)
    .map(([name, value]) => [name.replaceAll("_", " "), displayValue(value, "0")]);
}

export function renderPenaltyDrivers(target: HTMLDivElement, score: Dict): void {
  const rows = penaltyDriverRows(score);
  if (!rows.length) {
    target.textContent = "No penalty drivers reported.";
    return;
  }
  target.replaceChildren(...rows.map(([label, value]) => {
    const row = document.createElement("div");
    row.className = "driver-row";
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("strong");
    labelNode.textContent = label;
    valueNode.textContent = value;
    row.append(labelNode, valueNode);
    return row;
  }));
}

export function renderConflictList(list: HTMLOListElement, conflicts: string[]): void {
  const rows = conflicts.length ? conflicts : ["None"];
  list.replaceChildren(...rows.map((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }));
}

export function renderReadableDiagnostics(targets: ResultTargets, state: WebState, workerValue = ""): void {
  const meta = { ...(state.meta || {}), score: state.score || {} };
  const resultRows = buildResultRows(state, workerValue);
  renderKeyValueGrid(targets.resultSummary, resultRows);
  renderInsightRows(targets.insights, resultRows.slice(0, 5));
  renderPenaltyDrivers(targets.penaltyDrivers, state.score || {});
  renderConflictList(targets.sideConflicts, state.conflicts || []);
  renderConflictList(targets.resultsConflicts, state.conflicts || []);
  targets.rawDiagnostics.textContent = Object.keys(meta).length
    ? JSON.stringify(meta, null, 2)
    : "No solve has run.";
}
