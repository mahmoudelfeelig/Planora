import { renderReadableDiagnostics } from "./modules/results.js";
import { WORKSPACE_VIEWS, switchWorkspaceView } from "./modules/workspace_views.js";

type Dict<T = any> = Record<string, T>;
type Instance = {
  days: string[];
  slots_per_day: number;
  weeks: number[];
  activities: Dict<Dict>;
  staff: Dict<Dict>;
  rooms: Dict<Dict>;
  courses: Dict<Dict>;
  groups: Dict<Dict>;
  programs?: Dict<Dict>;
  hard_constraints?: Dict<boolean>;
};
type Schedule = Dict<Dict>;
type ScorePayload = {
  soft_penalty?: number;
  hard_conflict_count?: number;
  hard_conflicts?: string[];
  best_bound?: number;
  gap?: number;
  breakdown?: Dict<number>;
  drivers?: Dict[];
};

const byId = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
const state: {
  instance: Instance | null;
  schedule: Schedule;
  meta: Dict;
  conflicts: string[];
  score: ScorePayload;
  sessionId: string;
  jobId: string;
  heldActivityId: string;
  moveTargets: Dict[];
  history: Dict[];
  redo: Dict[];
  baseSnapshot: Dict | null;
} = {
  instance: null,
  schedule: {},
  meta: {},
  conflicts: [],
  score: {},
  sessionId: "",
  jobId: "",
  heldActivityId: "",
  moveTargets: [],
  history: [],
  redo: [],
  baseSnapshot: null,
};

const apiUrl = byId<HTMLInputElement>("api-url");
const preset = byId<HTMLSelectElement>("preset");
const solveButton = byId<HTMLButtonElement>("solve");
const portfolioButton = byId<HTMLButtonElement>("portfolio");
const solveJobButton = byId<HTMLButtonElement>("solve-job");
const pollJobButton = byId<HTMLButtonElement>("poll-job");
const scoreButton = byId<HTMLButtonElement>("score");
const improveButton = byId<HTMLButtonElement>("improve");
const cpPolishButton = byId<HTMLButtonElement>("cp-polish");
const exportButton = byId<HTMLButtonElement>("export-csv");
const moveButton = byId<HTMLButtonElement>("move-activity");
const lockButton = byId<HTMLButtonElement>("lock-activity");
const unlockButton = byId<HTMLButtonElement>("unlock-activity");
const saveProjectButton = byId<HTMLButtonElement>("save-project");
const undoButton = byId<HTMLButtonElement>("undo");
const redoButton = byId<HTMLButtonElement>("redo");
const revertButton = byId<HTMLButtonElement>("revert-base");
const clearLocksButton = byId<HTMLButtonElement>("clear-locks");

function endpoint(path: string): string {
  return `${apiUrl.value.trim().replace(/\/$/, "")}${path}`;
}

function toast(message: string): void {
  const node = byId<HTMLDivElement>("toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 2800);
}

async function fetchJson(path: string, options?: RequestInit): Promise<Dict> {
  const response = await fetch(endpoint(path), options);
  const payload = (await response.json()) as Dict;
  if (!response.ok || payload.error) throw new Error(String(payload.error || response.statusText));
  return payload;
}

function setConnection(online: boolean, text: string): void {
  const status = byId<HTMLSpanElement>("api-status");
  status.textContent = text;
  status.parentElement?.classList.toggle("online", online);
  status.parentElement?.classList.toggle("offline", !online);
}

async function refreshApi(): Promise<void> {
  try {
    await fetchJson("/health");
    setConnection(true, "API connected");
    const payload = await fetchJson("/presets");
    const presets = (payload.presets || []) as string[];
    preset.replaceChildren(...presets.map((name) => new Option(name.replaceAll("_", " "), name)));
    const capabilities = await fetchJson("/capabilities");
    const terms = (capabilities.focus_terms || []) as string[];
    const focus = byId<HTMLSelectElement>("focus-term");
    focus.replaceChildren(new Option("Overall", ""));
    terms.forEach((term) => focus.add(new Option(term.replaceAll("_", " "), term)));
    await refreshProjects();
  } catch (error) {
    setConnection(false, "API unavailable");
    toast(String(error));
  }
}

async function createSession(meta: Dict = {}): Promise<void> {
  if (!state.instance) return;
  const payload = await fetchJson("/sessions", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instance: state.instance, schedule: state.schedule, meta }),
  });
  state.sessionId = String(payload.session_id || "");
  byId<HTMLInputElement>("session-id").value = state.sessionId;
  setActionState();
}

async function sessionAction(action: string, payload: Dict = {}): Promise<Dict> {
  if (!state.sessionId) await createSession();
  if (!state.sessionId) throw new Error("No backend session.");
  const wrapped = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (wrapped.result || wrapped) as Dict;
}

function solverOptions(): Dict {
  return {
    room_mode: byId<HTMLSelectElement>("room-mode").value,
    objective_profile: byId<HTMLSelectElement>("profile").value,
    use_objective: byId<HTMLInputElement>("objective").checked,
    retry_without_objective: true,
    time_limit_seconds: Number(byId<HTMLInputElement>("time-limit").value),
    workers: Number(byId<HTMLInputElement>("workers").value),
  };
}

function instanceForSolve(): Instance {
  if (!state.instance) throw new Error("No instance loaded.");
  const instance = structuredClone(state.instance);
  instance.hard_constraints = {
    ...(instance.hard_constraints || {}),
    force_repeat_weekly_pattern: byId<HTMLInputElement>("repeat-pattern").checked,
  };
  return instance;
}

function hardConstraintOverrides(): Dict {
  return {
    force_repeat_weekly_pattern: byId<HTMLInputElement>("repeat-pattern").checked || byId<HTMLInputElement>("hard-repeat-week-settings").checked,
    week1_lectures_only: byId<HTMLInputElement>("hard-week1").checked,
    enforce_course_totals: byId<HTMLInputElement>("hard-course-totals").checked,
    block_profs: byId<HTMLInputElement>("hard-block-prof").checked,
    staff_daily_caps: byId<HTMLInputElement>("hard-staff-daily").checked,
    staff_weekly_caps: byId<HTMLInputElement>("hard-staff-weekly").checked,
    room_availability: byId<HTMLInputElement>("hard-room-availability").checked,
    travel_buffers: byId<HTMLInputElement>("hard-travel-buffers").checked,
    building_closures: byId<HTMLInputElement>("hard-building-closures").checked,
    calendar_rules: byId<HTMLInputElement>("hard-calendar-rules").checked,
    precedence_rules: byId<HTMLInputElement>("hard-precedence-rules").checked,
  };
}

function applySettingsToSidebar(): void {
  byId<HTMLSelectElement>("room-mode").value = byId<HTMLSelectElement>("settings-room-mode").value;
  byId<HTMLSelectElement>("profile").value = byId<HTMLSelectElement>("settings-profile").value;
  byId<HTMLInputElement>("time-limit").value = byId<HTMLInputElement>("settings-time-limit").value;
  byId<HTMLInputElement>("workers").value = byId<HTMLInputElement>("settings-workers").value;
  byId<HTMLInputElement>("repeat-pattern").checked = byId<HTMLInputElement>("hard-repeat-week-settings").checked;
  toast("Settings applied");
}

function setActionState(): void {
  const hasInstance = Boolean(state.instance);
  const hasSchedule = Boolean(Object.keys(state.schedule || {}).length);
  solveButton.disabled = !hasInstance;
  solveJobButton.disabled = !hasInstance;
  portfolioButton.disabled = !hasInstance;
  pollJobButton.disabled = !state.jobId;
  scoreButton.disabled = !hasInstance || !hasSchedule;
  improveButton.disabled = !hasInstance || !hasSchedule;
  cpPolishButton.disabled = !hasInstance || !hasSchedule || !byId<HTMLSelectElement>("focus-term").value;
  exportButton.disabled = !hasInstance || !hasSchedule;
  moveButton.disabled = !hasInstance || !hasSchedule;
  lockButton.disabled = !hasInstance || !hasSchedule;
  unlockButton.disabled = !hasInstance || !hasSchedule;
  saveProjectButton.disabled = !hasInstance;
  undoButton.disabled = !state.history.length;
  redoButton.disabled = !state.redo.length;
  revertButton.disabled = !state.baseSnapshot;
  clearLocksButton.disabled = !hasInstance || !Object.keys((state.instance as Dict | null)?.locked_activities || {}).length;
  [
    "conflicts-rescore", "conflicts-improve", "hold-selected", "show-targets",
    "release-held", "why-run", "generator-export-json",
  ].forEach((id) => {
    const button = document.getElementById(id) as HTMLButtonElement | null;
    if (button) button.disabled = !hasSchedule;
  });
  byId<HTMLButtonElement>("release-held").disabled = !state.heldActivityId;
}

function snapshot(label: string): Dict {
  return {
    label,
    at: new Date().toLocaleTimeString(),
    instance: structuredClone(state.instance),
    schedule: structuredClone(state.schedule),
    meta: structuredClone(state.meta),
    conflicts: structuredClone(state.conflicts),
    score: structuredClone(state.score),
  };
}

function pushHistory(label: string): void {
  if (!state.instance) return;
  state.history.push(snapshot(label));
  state.redo = [];
  if (state.history.length > 50) state.history.shift();
  renderHistory();
}

function restoreSnapshot(snap: Dict, status: string): void {
  state.instance = structuredClone(snap.instance || null);
  state.schedule = structuredClone(snap.schedule || {});
  state.meta = structuredClone(snap.meta || {});
  state.conflicts = structuredClone(snap.conflicts || []);
  state.score = structuredClone(snap.score || {});
  populateFilters();
  populateActivityControls();
  updateMetrics(status);
  renderDiagnostics();
  renderSchedule();
}

function lockCount(): number {
  return Object.keys((state.instance as Dict | null)?.locked_activities || {}).length;
}

function entityName(collection: Dict<Dict>, id: unknown, fallback: string): string {
  const row = collection[String(id)] || {};
  return String(row.name || row.code || fallback);
}

function populateFilters(): void {
  if (!state.instance) return;
  const weeks = byId<HTMLSelectElement>("week-filter");
  weeks.replaceChildren(...state.instance.weeks.map((week) => new Option(`Week ${week}`, String(week))));
  const groups = byId<HTMLSelectElement>("group-filter");
  groups.replaceChildren(new Option("All groups", ""));
  Object.entries(state.instance.groups).forEach(([id, group]) => {
    groups.add(new Option(String(group.name || `Group ${id}`), id));
  });
  const days = byId<HTMLSelectElement>("move-day");
  days.replaceChildren(...state.instance.days.map((day) => new Option(String(day), String(day))));
  byId<HTMLSelectElement>("why-day").replaceChildren(...state.instance.days.map((day) => new Option(String(day), String(day))));
  byId<HTMLSelectElement>("why-week").replaceChildren(...state.instance.weeks.map((week) => new Option(`Week ${week}`, String(week))));
  populateHeatmapEntities();
}

function populateActivityControls(): void {
  const select = byId<HTMLSelectElement>("activity-select");
  select.replaceChildren();
  if (!state.instance || !Object.keys(state.schedule).length) return;
  Object.entries(state.schedule)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .forEach(([id, info]) => {
      const course = entityName(state.instance!.courses, info.course_id, `Course ${info.course_id}`);
      select.add(new Option(`A${id} ${course} W${info.week} ${info.day} S${Number(info.slot) + 1}`, id));
    });
  const whySelect = byId<HTMLSelectElement>("why-activity");
  whySelect.replaceChildren(...Array.from(select.options).map((option) => new Option(option.text, option.value)));
  syncMoveFieldsFromActivity();
}

function populateHeatmapEntities(): void {
  if (!state.instance) return;
  const kind = byId<HTMLSelectElement>("heatmap-kind").value;
  const target = byId<HTMLSelectElement>("heatmap-entity");
  const collection = kind === "staff" ? state.instance.staff : state.instance.groups;
  target.replaceChildren(...Object.entries(collection).map(([id, row]) => new Option(String(row.name || row.code || id), id)));
}

function syncMoveFieldsFromActivity(): void {
  const id = byId<HTMLSelectElement>("activity-select").value;
  const info = state.schedule[String(id)];
  if (!info) return;
  byId<HTMLSelectElement>("move-day").value = String(info.day);
  byId<HTMLInputElement>("move-slot").value = String(info.slot);
  byId<HTMLInputElement>("move-room").value = info.room_id == null ? "" : String(info.room_id);
  byId<HTMLInputElement>("move-staff").value = info.staff_id == null ? "" : String(info.staff_id);
}

function updateMetrics(status = "Ready"): void {
  const inst = state.instance;
  byId("metric-activities").textContent = String(inst ? Object.keys(inst.activities).length : 0);
  byId("metric-staff").textContent = String(inst ? Object.keys(inst.staff).length : 0);
  byId("metric-rooms").textContent = String(inst ? Object.keys(inst.rooms).length : 0);
  byId("metric-conflicts").textContent = String(state.score.hard_conflict_count ?? state.conflicts.length);
  byId("metric-penalty").textContent = String(state.score.soft_penalty ?? 0);
  byId("metric-status").textContent = status;
  setActionState();
  updateWorkflowState(status);
}

function updateWorkflowState(status: string): void {
  const hasInstance = Boolean(state.instance);
  const hasSchedule = Boolean(Object.keys(state.schedule || {}).length);
  const conflictCount = Number(state.score.hard_conflict_count ?? state.conflicts.length ?? 0);
  byId("data-state").textContent = hasInstance
    ? `${Object.keys(state.instance!.activities).length} activities loaded`
    : "No scenario loaded";
  byId("solve-state").textContent = hasInstance
    ? hasSchedule ? "Schedule available" : status === "Running" ? "Running" : "Ready"
    : "Waiting for data";
  byId("improve-state").textContent = hasSchedule
    ? `Penalty ${state.score.soft_penalty ?? 0}`
    : "No schedule yet";
  byId("edit-state").textContent = hasSchedule
    ? conflictCount ? `${conflictCount} conflicts to inspect` : "Conflict-free"
    : "Select an activity";
  byId("board-subtitle").textContent = hasInstance
    ? hasSchedule ? "Review the generated timetable by week, group, or search term." : "Scenario loaded. Run Solve to create a timetable."
    : "Choose a preset or import a file to begin.";
  document.querySelectorAll<HTMLElement>(".step-card[data-step]").forEach((card) => {
    const step = Number(card.dataset.step || "0");
    const ready =
      (step === 1 && hasInstance) ||
      (step === 2 && hasSchedule) ||
      (step === 3 && hasSchedule) ||
      (step === 4 && hasSchedule);
    const active =
      (!hasInstance && step === 1) ||
      (hasInstance && !hasSchedule && step === 2) ||
      (hasSchedule && conflictCount === 0 && step === 3) ||
      (hasSchedule && conflictCount > 0 && step === 4);
    card.classList.toggle("ready", ready);
    card.classList.toggle("active", active);
  });
}

function renderDiagnostics(): void {
  renderReadableDiagnostics({
    resultSummary: byId<HTMLDivElement>("result-summary"),
    insights: byId<HTMLDivElement>("diagnostic-content"),
    penaltyDrivers: byId<HTMLDivElement>("penalty-drivers"),
    sideConflicts: byId<HTMLOListElement>("conflict-list"),
    resultsConflicts: byId<HTMLOListElement>("results-conflict-list"),
    rawDiagnostics: byId<HTMLElement>("raw-diagnostics"),
  }, state, byId<HTMLInputElement>("workers").value);
  renderSimpleConflictList("conflict-review-list");
  renderFairness();
  renderHeatmap();
  renderHistory();
}

function renderSimpleConflictList(targetId: string): void {
  const list = byId<HTMLOListElement>(targetId);
  const rows = state.conflicts.length ? state.conflicts : ["None"];
  list.replaceChildren(...rows.map((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }));
}

function renderImprovementProgress(events: Dict[]): void {
  const target = byId<HTMLDivElement>("improve-progress");
  const rows = (events || []).slice(-12);
  if (!rows.length) {
    target.textContent = "No local-search progress yet.";
    return;
  }
  target.replaceChildren(...rows.map((event) => {
    const row = document.createElement("div");
    row.className = "progress-update";
    row.textContent = `Iter ${event.iteration}: current ${event.current_penalty}, best ${event.best_penalty}`;
    return row;
  }));
}

function renderHistory(): void {
  const list = byId<HTMLOListElement>("history-list");
  const rows = state.history.length
    ? state.history.slice().reverse().map((snap) => `${snap.at || ""} ${snap.label || "Change"}`.trim())
    : ["No edits yet."];
  list.replaceChildren(...rows.map((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }));
}

function scheduleRows(): Dict[] {
  return Object.entries(state.schedule || {}).map(([id, row]) => ({ id, ...row }));
}

function renderFairness(): void {
  const rows = scheduleRows();
  const groupLoads = new Map<string, number>();
  const staffLoads = new Map<string, number>();
  rows.forEach((event) => {
    ((event.group_ids || []) as unknown[]).forEach((gid) => groupLoads.set(String(gid), (groupLoads.get(String(gid)) || 0) + 1));
    if (event.staff_id != null) staffLoads.set(String(event.staff_id), (staffLoads.get(String(event.staff_id)) || 0) + 1);
  });
  const makeRows = (loads: Map<string, number>, collection: Dict<Dict>, fallback: string): HTMLDivElement[] => {
    const values = [...loads.values()];
    const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
    const header = document.createElement("div");
    header.className = "table-like-row header";
    ["Name", "Total slots", "Average", "Difference", "Score"].forEach((text) => {
      const cell = document.createElement("span"); cell.textContent = text; header.append(cell);
    });
    return [header, ...[...loads.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20).map(([id, load]) => {
      const row = document.createElement("div");
      row.className = "table-like-row";
      const diff = load - avg;
      [entityName(collection, id, `${fallback} ${id}`), String(load), String(Math.round(avg * 10) / 10), String(Math.round(diff * 10) / 10), String(Math.abs(Math.round(diff * 10) / 10))].forEach((text) => {
        const cell = document.createElement("span"); cell.textContent = text; row.append(cell);
      });
      return row;
    })];
  };
  byId("fairness-summary").textContent = rows.length
    ? `Computed from ${rows.length} scheduled activities. Lower difference from average is better.`
    : "Load and score a schedule to inspect group and staff fairness.";
  byId<HTMLDivElement>("fairness-group-table").replaceChildren(...makeRows(groupLoads, state.instance?.groups || {}, "Group"));
  byId<HTMLDivElement>("fairness-staff-table").replaceChildren(...makeRows(staffLoads, state.instance?.staff || {}, "Staff"));
}

function renderHeatmap(): void {
  const target = byId<HTMLDivElement>("heatmap-table");
  const kind = byId<HTMLSelectElement>("heatmap-kind").value;
  const entity = byId<HTMLSelectElement>("heatmap-entity").value;
  if (!state.instance || !Object.keys(state.schedule).length || !entity) {
    target.textContent = "Load a schedule and choose an entity.";
    return;
  }
  const counts = new Map<string, number>();
  state.instance.days.forEach((day) => counts.set(String(day), 0));
  scheduleRows().forEach((event) => {
    const matches = kind === "staff"
      ? String(event.staff_id) === entity
      : ((event.group_ids || []) as unknown[]).map(String).includes(entity);
    if (matches) counts.set(String(event.day), (counts.get(String(event.day)) || 0) + 1);
  });
  const max = Math.max(1, ...counts.values());
  target.replaceChildren(...[...counts.entries()].map(([day, value]) => {
    const cell = document.createElement("div");
    cell.className = "heatmap-cell";
    cell.style.background = `rgba(111, 85, 188, ${0.22 + 0.58 * (value / max)})`;
    cell.textContent = `${day}: ${value}`;
    return cell;
  }));
}

function moveTargetFor(day: string, slot: number): Dict | undefined {
  const week = Number(byId<HTMLSelectElement>("week-filter").value || 0);
  return state.moveTargets.find((target) =>
    Number(target.week) === week &&
    String(target.day) === String(day) &&
    Number(target.slot) === Number(slot)
  );
}

function renderSchedule(): void {
  const inst = state.instance;
  const table = byId<HTMLTableElement>("schedule-table");
  const empty = byId<HTMLDivElement>("empty-state");
  if (!inst || !Object.keys(state.schedule).length) {
    table.hidden = true; empty.hidden = false; return;
  }
  empty.hidden = true; table.hidden = false;
  const week = Number(byId<HTMLSelectElement>("week-filter").value || inst.weeks[0]);
  const group = byId<HTMLSelectElement>("group-filter").value;
  const query = byId<HTMLInputElement>("search").value.trim().toLowerCase();
  const head = table.tHead?.rows[0] || table.createTHead().insertRow();
  head.replaceChildren();
  ["Day", ...Array.from({ length: inst.slots_per_day }, (_, index) => `Slot ${index + 1}`)].forEach((label) => {
    const th = document.createElement("th"); th.textContent = label; head.append(th);
  });
  const body = table.tBodies[0] || table.createTBody(); body.replaceChildren();
  inst.days.forEach((day) => {
    const row = body.insertRow(); row.insertCell().textContent = day;
    for (let slot = 0; slot < inst.slots_per_day; slot += 1) {
      const cell = row.insertCell();
      cell.dataset.day = String(day);
      cell.dataset.slot = String(slot);
      const target = moveTargetFor(String(day), slot);
      if (target) {
        cell.classList.add("move-target", target.ok ? "viable" : "blocked");
        const badge = document.createElement("div");
        const delta = Number(target.delta || 0);
        badge.className = `delta-badge ${delta <= 0 ? "better" : "worse"}`;
        badge.textContent = target.ok ? `${delta >= 0 ? "+" : ""}${delta}` : `blocked · ${target.hard_conflict_count}`;
        cell.append(badge);
      }
      Object.entries(state.schedule).forEach(([activityId, event]) => {
        if (Number(event.week) !== week || String(event.day) !== day || Number(event.slot) !== slot) return;
        const groupIds = (event.group_ids || []) as unknown[];
        if (group && !groupIds.map(String).includes(group)) return;
        const course = entityName(inst.courses, event.course_id, `Course ${event.course_id}`);
        const room = entityName(inst.rooms, event.room_id, `Room ${event.room_id}`);
        const staff = entityName(inst.staff, event.staff_id, `Staff ${event.staff_id}`);
        const haystack = `${course} ${room} ${staff} ${activityId}`.toLowerCase();
        if (query && !haystack.includes(query)) return;
        const card = document.createElement("div");
        card.className = `event ${String(event.kind || "").toLowerCase()}`;
        card.dataset.activityId = activityId;
        if (String(activityId) === String(state.heldActivityId)) card.classList.add("held");
        card.innerHTML = `<strong></strong><span></span><span></span>`;
        (card.children[0] as HTMLElement).textContent = course;
        (card.children[1] as HTMLElement).textContent = `${event.kind} · ${staff}`;
        (card.children[2] as HTMLElement).textContent = room;
        cell.append(card);
      });
    }
  });
}

function acceptInstance(instance: Instance): void {
  state.instance = instance;
  state.schedule = {};
  state.meta = {};
  state.conflicts = [];
  state.score = {};
  state.sessionId = "";
  state.heldActivityId = "";
  state.moveTargets = [];
  populateFilters(); updateMetrics(); renderDiagnostics(); renderSchedule();
  populateActivityControls();
  byId<HTMLInputElement>("session-id").value = "";
}

function acceptSchedule(schedule: Schedule, meta: Dict = {}, score: ScorePayload = {}): void {
  state.schedule = schedule || {};
  state.meta = meta || {};
  state.score = score || {};
  state.conflicts = (score.hard_conflicts || state.conflicts || []) as string[];
  state.moveTargets = [];
  updateMetrics(Object.keys(state.schedule).length ? "Schedule loaded" : "No schedule");
  renderDiagnostics();
  renderSchedule();
  populateActivityControls();
  if (!state.baseSnapshot && Object.keys(state.schedule).length) {
    state.baseSnapshot = snapshot("Base schedule");
  }
}

async function loadPreset(): Promise<void> {
  try {
    byId<HTMLButtonElement>("load-preset").disabled = true;
    const payload = await fetchJson(`/preset/${encodeURIComponent(preset.value)}`);
    acceptInstance(payload.instance as Instance);
    await createSession({ source: "preset", mode: preset.value });
    toast(`Loaded ${preset.value}`);
  } catch (error) { toast(String(error)); }
  finally { byId<HTMLButtonElement>("load-preset").disabled = false; }
}

async function solve(): Promise<void> {
  if (!state.instance) return;
  solveButton.disabled = true; solveButton.textContent = "Solving..."; updateMetrics("Running");
  try {
    if (!state.sessionId) await createSession();
    const payload = state.sessionId
      ? await sessionAction("solve", { options: solverOptions(), hard_constraints: hardConstraintOverrides() })
      : await fetchJson("/solve", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instance: instanceForSolve(), options: solverOptions() }),
        });
    if (Object.keys(state.schedule).length) pushHistory("Before solve");
    state.conflicts = (payload.hard_conflicts || []) as string[];
    acceptSchedule((payload.schedule || {}) as Schedule, (payload.meta || {}) as Dict, ((payload.meta as Dict)?.quality || {}) as ScorePayload);
    updateMetrics(Object.keys(state.schedule).length ? "Feasible" : `Status ${payload.status}`);
  } catch (error) { updateMetrics("Failed"); toast(String(error)); }
  finally { solveButton.disabled = false; solveButton.textContent = "Solve schedule"; }
}

async function startSolveJob(): Promise<void> {
  if (!state.instance) return;
  if (!state.sessionId) await createSession();
  const payload = await fetchJson("/jobs/solve", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId, options: solverOptions(), hard_constraints: hardConstraintOverrides() }),
  });
  state.jobId = String(payload.job_id || "");
  byId<HTMLInputElement>("job-id").value = state.jobId;
  updateMetrics("Job queued");
}

async function pollJob(): Promise<void> {
  if (!state.jobId) return;
  const eventText = await fetch(endpoint(`/jobs/${encodeURIComponent(state.jobId)}/events`)).then((r) => r.text());
  const payload = await fetchJson(`/jobs/${encodeURIComponent(state.jobId)}`);
  state.meta = { ...(state.meta || {}), job: payload, job_event_stream: eventText };
  if (payload.status === "complete" && payload.result) {
    const result = payload.result as Dict;
    if (result.schedule) {
      if (Object.keys(state.schedule).length) pushHistory("Before job result");
      acceptSchedule((result.schedule || {}) as Schedule, (result.meta || {}) as Dict, ((result.meta as Dict)?.quality || {}) as ScorePayload);
    }
    updateMetrics("Job complete");
  } else {
    updateMetrics(`Job ${payload.status}`);
    renderDiagnostics();
  }
}

async function runPortfolio(): Promise<void> {
  if (!state.instance) return;
  portfolioButton.disabled = true; portfolioButton.textContent = "Running...";
  try {
    const payload = state.sessionId
      ? await sessionAction("portfolio", { options: solverOptions(), hard_constraints: hardConstraintOverrides() })
      : await fetchJson("/portfolio", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instance: instanceForSolve(), options: solverOptions() }),
        });
    const candidates = (payload.candidates || []) as Dict[];
    const best = candidates[Number(payload.best_index)];
    if (!best) throw new Error("No feasible portfolio candidate.");
    const result = (best.result || {}) as Dict;
    if (Object.keys(state.schedule).length) pushHistory("Before portfolio");
    acceptSchedule((result.schedule || {}) as Schedule, (result.meta || {}) as Dict, ((result.meta as Dict)?.quality || {}) as ScorePayload);
    toast(`Best profile: ${best.name}`);
  } catch (error) { toast(String(error)); }
  finally { portfolioButton.disabled = false; portfolioButton.textContent = "Run portfolio"; }
}

async function scoreCurrent(): Promise<void> {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  const payload = state.sessionId
    ? await sessionAction("score")
    : await fetchJson("/score", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instance: state.instance, schedule: state.schedule }),
      });
  state.score = payload as ScorePayload;
  state.conflicts = (payload.hard_conflicts || []) as string[];
  updateMetrics("Scored");
  renderDiagnostics();
}

async function improve(): Promise<void> {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  improveButton.disabled = true; improveButton.textContent = "Improving...";
  try {
    const body = {
        focus_term: byId<HTMLSelectElement>("focus-term").value,
        options: {
          iterations: Number(byId<HTMLInputElement>("improve-iters").value),
          max_seconds: Number(byId<HTMLInputElement>("improve-seconds").value) || null,
          progress_every: 10,
        },
      };
    const payload = state.sessionId
      ? await sessionAction("improve", body)
      : await fetchJson("/improve", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instance: state.instance, schedule: state.schedule, ...body }),
        });
    pushHistory("Before improve");
    acceptSchedule((payload.schedule || {}) as Schedule, (payload.meta || {}) as Dict, (payload.global_after || payload.after || {}) as ScorePayload);
    renderImprovementProgress((payload.meta as Dict)?.progress_events as Dict[] || []);
    toast(`Penalty ${payload.before?.soft_penalty ?? "?"} -> ${payload.global_after?.soft_penalty ?? payload.after?.soft_penalty ?? "?"}`);
  } catch (error) { toast(String(error)); }
  finally { improveButton.disabled = false; improveButton.textContent = "Improve"; }
}

async function cpPolish(): Promise<void> {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  const focus = byId<HTMLSelectElement>("focus-term").value;
  if (!focus) { toast("Choose a focus term first."); return; }
  cpPolishButton.disabled = true; cpPolishButton.textContent = "Polishing...";
  try {
    const body = {
        focus_term: focus,
        affected_limit: 100,
        options: { ...solverOptions(), use_objective: true, objective_profile: "balanced" },
      };
    const payload = state.sessionId
      ? await sessionAction("cp-polish", body)
      : await fetchJson("/cp-polish", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instance: state.instance, schedule: state.schedule, ...body }),
        });
    pushHistory("Before CP polish");
    acceptSchedule((payload.schedule || {}) as Schedule, (payload.meta || {}) as Dict, ((payload.meta as Dict)?.quality || {}) as ScorePayload);
    updateMetrics(Object.keys(state.schedule).length ? "Polished" : `Status ${payload.status}`);
  } catch (error) { toast(String(error)); }
  finally { cpPolishButton.disabled = false; cpPolishButton.textContent = "Focused CP-SAT polish"; }
}

async function exportCsv(): Promise<void> {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  try {
    const payload = state.sessionId
      ? await sessionAction("export-csv", { filename: "planora-schedule.csv" })
      : await fetchJson("/export/csv", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instance: state.instance, schedule: state.schedule, filename: "planora-schedule.csv" }),
        });
    const blob = new Blob([String(payload.content || "")], { type: String(payload.content_type || "text/csv") });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = String(payload.filename || "planora-schedule.csv");
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) { toast(String(error)); }
}

async function moveActivity(): Promise<void> {
  const activityId = byId<HTMLSelectElement>("activity-select").value;
  if (!activityId) return;
  const payload = await sessionAction("move", {
    activity_id: Number(activityId),
    day: byId<HTMLSelectElement>("move-day").value,
    slot: Number(byId<HTMLInputElement>("move-slot").value),
    room_id: Number(byId<HTMLInputElement>("move-room").value),
    staff_id: Number(byId<HTMLInputElement>("move-staff").value),
    enforce_hard_conflict_free: !byId<HTMLInputElement>("allow-conflict-move").checked,
  });
  pushHistory("Before move");
  acceptSchedule((payload.schedule || state.schedule) as Schedule, state.meta, (payload.score || {}) as ScorePayload);
  toast(payload.ok ? "Moved activity" : "Move blocked by hard conflicts");
}

async function loadMoveTargets(): Promise<void> {
  const activityId = state.heldActivityId || byId<HTMLSelectElement>("activity-select").value;
  if (!activityId || !state.instance || !Object.keys(state.schedule).length) return;
  const current = state.schedule[String(activityId)] || {};
  const payload = await sessionAction("move-deltas", {
    activity_id: Number(activityId),
    week: Number(byId<HTMLSelectElement>("week-filter").value || current.week),
    room_id: current.room_id,
    staff_id: current.staff_id,
  });
  state.heldActivityId = String(activityId);
  state.moveTargets = (payload.targets || []) as Dict[];
  const viable = state.moveTargets.filter((target) => target.ok).length;
  byId("hold-status").textContent = `Holding A${activityId}. ${viable}/${state.moveTargets.length} visible targets are viable; negative deltas improve the score.`;
  setActionState();
  renderSchedule();
}

async function moveHeldToTarget(day: string, slot: number): Promise<void> {
  if (!state.heldActivityId) return;
  const target = moveTargetFor(day, slot);
  if (!target) return;
  if (!target.ok) {
    byId("hold-status").textContent = `Target blocked: ${(target.hard_conflicts || []).slice(0, 2).join(" | ") || "hard conflict"}`;
    return;
  }
  pushHistory("Before board move");
  const payload = await sessionAction("move", {
    activity_id: Number(state.heldActivityId),
    week: Number(target.week),
    day: String(target.day),
    slot: Number(target.slot),
    room_id: target.room_id,
    staff_id: target.staff_id,
    enforce_hard_conflict_free: true,
  });
  acceptSchedule((payload.schedule || state.schedule) as Schedule, state.meta, (payload.score || {}) as ScorePayload);
  state.heldActivityId = "";
  state.moveTargets = [];
  byId("hold-status").textContent = payload.ok ? "Activity moved. Hold another activity to preview new targets." : "Move was blocked by hard conflicts.";
  setActionState();
}

async function lockActivity(): Promise<void> {
  const activityId = byId<HTMLSelectElement>("activity-select").value;
  if (!activityId) return;
  const payload = await sessionAction("lock", { activity_id: Number(activityId), fields: ["day", "slot", "room_id"] });
  pushHistory("Before lock");
  state.instance = payload.instance as Instance;
  toast("Activity locked");
  setActionState();
}

async function unlockActivity(): Promise<void> {
  const activityId = byId<HTMLSelectElement>("activity-select").value;
  if (!activityId) return;
  const payload = await sessionAction("unlock", { activity_id: Number(activityId) });
  pushHistory("Before unlock");
  state.instance = payload.instance as Instance;
  toast("Activity unlocked");
  setActionState();
}

async function clearLocks(): Promise<void> {
  if (!state.instance) return;
  pushHistory("Before clear locks");
  const payload = await sessionAction("unlock", {});
  state.instance = payload.instance as Instance;
  toast(`Cleared locks (${lockCount()} remaining)`);
  setActionState();
  renderDiagnostics();
}

function undo(): void {
  const snap = state.history.pop();
  if (!snap) return;
  state.redo.push(snapshot("Redo point"));
  restoreSnapshot(snap, "Undo");
}

function redo(): void {
  const snap = state.redo.pop();
  if (!snap) return;
  state.history.push(snapshot("Undo point"));
  restoreSnapshot(snap, "Redo");
}

function revertBase(): void {
  if (!state.baseSnapshot) return;
  pushHistory("Before revert base");
  restoreSnapshot(state.baseSnapshot, "Reverted");
}

function explainWhySlot(): void {
  const activityId = byId<HTMLSelectElement>("why-activity").value;
  if (!activityId) return;
  const event = state.schedule[String(activityId)];
  const day = byId<HTMLSelectElement>("why-day").value;
  const slot = Number(byId<HTMLInputElement>("why-slot").value);
  const blockers = scheduleRows().filter((other) => {
    if (String(other.id) === String(activityId)) return false;
    if (Number(other.week) !== Number(byId<HTMLSelectElement>("why-week").value)) return false;
    if (String(other.day) !== day || Number(other.slot) !== slot) return false;
    const sameStaff = event?.staff_id != null && String(other.staff_id) === String(event.staff_id);
    const sameRoom = event?.room_id != null && String(other.room_id) === String(event.room_id);
    const groups = new Set(((event?.group_ids || []) as unknown[]).map(String));
    const sameGroup = ((other.group_ids || []) as unknown[]).some((gid) => groups.has(String(gid)));
    return sameStaff || sameRoom || sameGroup;
  });
  byId("why-output").textContent = blockers.length
    ? `Blocked by ${blockers.length} activity/activities at that slot:\n` + blockers.slice(0, 12).map((row) => `- A${row.id} ${entityName(state.instance?.courses || {}, row.course_id, `Course ${row.course_id}`)}`).join("\n")
    : "No direct staff, room, or group overlap found for that candidate slot.";
}

function exportInstanceJson(): void {
  if (!state.instance) return;
  const blob = new Blob([JSON.stringify(state.instance, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "planora-instance.json";
  link.click();
  URL.revokeObjectURL(url);
}

async function refreshProjects(): Promise<void> {
  const select = byId<HTMLSelectElement>("project-select");
  try {
    const payload = await fetchJson("/projects");
    select.replaceChildren(...((payload.projects || []) as Dict[]).map((row) => new Option(String(row.name), String(row.name))));
  } catch (_error) {
    select.replaceChildren();
  }
}

async function saveProject(): Promise<void> {
  if (!state.instance) return;
  const name = byId<HTMLInputElement>("project-name").value || "web-project";
  await fetchJson("/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, session_id: state.sessionId, instance: state.instance, schedule: state.schedule, meta: state.meta }),
  });
  await refreshProjects();
  toast(`Saved ${name}`);
}

async function loadProject(): Promise<void> {
  const name = byId<HTMLSelectElement>("project-select").value;
  if (!name) return;
  const payload = await fetchJson(`/projects/${encodeURIComponent(name)}`);
  acceptInstance(payload.instance as Instance);
  acceptSchedule((payload.schedule || {}) as Schedule, (payload.meta || {}) as Dict, {});
  await createSession({ source: "project", name });
  toast(`Loaded ${name}`);
}

byId("load-preset").addEventListener("click", loadPreset);
solveButton.addEventListener("click", solve);
solveJobButton.addEventListener("click", startSolveJob);
pollJobButton.addEventListener("click", pollJob);
portfolioButton.addEventListener("click", runPortfolio);
scoreButton.addEventListener("click", () => { scoreCurrent().catch((error) => toast(String(error))); });
improveButton.addEventListener("click", improve);
cpPolishButton.addEventListener("click", cpPolish);
exportButton.addEventListener("click", exportCsv);
moveButton.addEventListener("click", () => { moveActivity().catch((error) => toast(String(error))); });
lockButton.addEventListener("click", () => { lockActivity().catch((error) => toast(String(error))); });
unlockButton.addEventListener("click", () => { unlockActivity().catch((error) => toast(String(error))); });
saveProjectButton.addEventListener("click", () => { saveProject().catch((error) => toast(String(error))); });
byId("refresh-projects").addEventListener("click", () => { refreshProjects().catch((error) => toast(String(error))); });
byId("load-project").addEventListener("click", () => { loadProject().catch((error) => toast(String(error))); });
byId("openapi").addEventListener("click", () => window.open(endpoint("/openapi.json"), "_blank"));
WORKSPACE_VIEWS.forEach((view) => {
  byId(`view-${view}`).addEventListener("click", () => switchWorkspaceView(view));
});
byId("conflicts-rescore").addEventListener("click", () => { scoreCurrent().catch((error) => toast(String(error))); });
byId("conflicts-improve").addEventListener("click", improve);
byId("apply-settings").addEventListener("click", applySettingsToSidebar);
byId("undo").addEventListener("click", undo);
byId("redo").addEventListener("click", redo);
byId("revert-base").addEventListener("click", revertBase);
byId("clear-locks").addEventListener("click", () => { clearLocks().catch((error) => toast(String(error))); });
byId("hold-selected").addEventListener("click", () => {
  state.heldActivityId = byId<HTMLSelectElement>("activity-select").value;
  loadMoveTargets().catch((error) => toast(String(error)));
});
byId("show-targets").addEventListener("click", () => { loadMoveTargets().catch((error) => toast(String(error))); });
byId("release-held").addEventListener("click", () => {
  state.heldActivityId = "";
  state.moveTargets = [];
  byId("hold-status").textContent = "Hold released. Select an activity to preview target slots.";
  setActionState();
  renderSchedule();
});
byId("schedule-table").addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const cell = target.closest<HTMLTableCellElement>("td[data-day][data-slot]");
  if (!cell || !state.heldActivityId) return;
  moveHeldToTarget(String(cell.dataset.day), Number(cell.dataset.slot)).catch((error) => toast(String(error)));
});
byId("why-run").addEventListener("click", explainWhySlot);
byId("heatmap-kind").addEventListener("change", () => { populateHeatmapEntities(); renderHeatmap(); });
byId("heatmap-entity").addEventListener("change", renderHeatmap);
byId("heatmap-metric").addEventListener("change", renderHeatmap);
byId("generator-load-current").addEventListener("click", () => {
  if (!state.instance) return;
  byId<HTMLInputElement>("gen-programs").value = String(Object.keys(state.instance.programs || {}).length || 0);
  byId<HTMLInputElement>("gen-groups").value = String(Object.keys(state.instance.groups || {}).length || 0);
  byId<HTMLInputElement>("gen-courses").value = String(Object.keys(state.instance.courses || {}).length || 0);
  byId<HTMLInputElement>("gen-staff").value = String(Object.keys(state.instance.staff || {}).length || 0);
  byId<HTMLInputElement>("gen-rooms").value = String(Object.keys(state.instance.rooms || {}).length || 0);
});
byId("generator-export-json").addEventListener("click", exportInstanceJson);
apiUrl.addEventListener("change", refreshApi);
byId<HTMLInputElement>("instance-file").addEventListener("change", async (event) => {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
  try { acceptInstance(JSON.parse(await file.text()) as Instance); await createSession({ source: "instance_json", filename: file.name }); toast(`Loaded ${file.name}`); }
  catch (error) { toast(`Invalid instance JSON: ${error}`); }
});
byId<HTMLInputElement>("csv-file").addEventListener("change", async (event) => {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
  try {
    const payload = await fetchJson("/import/csv", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content: await file.text(),
        lock_imported: byId<HTMLInputElement>("lock-imported").checked,
      }),
    });
    state.instance = payload.instance as Instance;
    populateFilters();
    acceptSchedule((payload.schedule || {}) as Schedule, (payload.meta || {}) as Dict, (payload.score || {}) as ScorePayload);
    await createSession({ source: "timetable_csv", filename: file.name });
    toast(`Imported ${file.name}`);
  } catch (error) { toast(`CSV import failed: ${error}`); }
});
["week-filter", "group-filter", "search"].forEach((id) => byId(id).addEventListener("input", () => {
  state.moveTargets = [];
  if (id === "week-filter" && state.heldActivityId) loadMoveTargets().catch((error) => toast(String(error)));
  else renderSchedule();
}));
byId("focus-term").addEventListener("change", setActionState);
byId("activity-select").addEventListener("change", () => {
  state.heldActivityId = "";
  state.moveTargets = [];
  syncMoveFieldsFromActivity();
  byId("hold-status").textContent = "Selection changed. Hold it to preview viable target slots.";
  setActionState();
  renderSchedule();
});
refreshApi();
