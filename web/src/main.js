import { renderReadableDiagnostics } from "./modules/results.js";
import { WORKSPACE_VIEWS, switchWorkspaceView } from "./modules/workspace_views.js";

const byId = (id) => document.getElementById(id);

const state = {
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

const apiUrl = byId("api-url");
const preset = byId("preset");
const solveButton = byId("solve");
const solveJobButton = byId("solve-job");
const pollJobButton = byId("poll-job");
const portfolioButton = byId("portfolio");
const scoreButton = byId("score");
const improveButton = byId("improve");
const cpPolishButton = byId("cp-polish");
const exportButton = byId("export-csv");
const moveButton = byId("move-activity");
const lockButton = byId("lock-activity");
const unlockButton = byId("unlock-activity");
const saveProjectButton = byId("save-project");
const undoButton = byId("undo");
const redoButton = byId("redo");
const revertButton = byId("revert-base");
const clearLocksButton = byId("clear-locks");

function endpoint(path) {
  return `${apiUrl.value.trim().replace(/\/$/, "")}${path}`;
}

function toast(message) {
  const node = byId("toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 2800);
}

async function fetchJson(path, options) {
  const response = await fetch(endpoint(path), options);
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(String(payload.error || response.statusText));
  return payload;
}

function setConnection(online, text) {
  const status = byId("api-status");
  status.textContent = text;
  status.parentElement?.classList.toggle("online", online);
  status.parentElement?.classList.toggle("offline", !online);
}

async function refreshApi() {
  try {
    await fetchJson("/health");
    setConnection(true, "API connected");
    const presets = await fetchJson("/presets");
    preset.replaceChildren(...(presets.presets || []).map((name) => new Option(name.replaceAll("_", " "), name)));
    const capabilities = await fetchJson("/capabilities");
    const focus = byId("focus-term");
    focus.replaceChildren(new Option("Overall", ""));
    (capabilities.focus_terms || []).forEach((term) => focus.add(new Option(term.replaceAll("_", " "), term)));
    await refreshProjects();
  } catch (error) {
    setConnection(false, "API unavailable");
    toast(String(error));
  }
}

function solverOptions() {
  return {
    room_mode: byId("room-mode").value,
    objective_profile: byId("profile").value,
    use_objective: byId("objective").checked,
    retry_without_objective: true,
    time_limit_seconds: Number(byId("time-limit").value),
    workers: Number(byId("workers").value),
  };
}

function setActionState() {
  const hasInstance = Boolean(state.instance);
  const hasSchedule = Boolean(Object.keys(state.schedule || {}).length);
  solveButton.disabled = !hasInstance;
  solveJobButton.disabled = !hasInstance;
  portfolioButton.disabled = !hasInstance;
  pollJobButton.disabled = !state.jobId;
  scoreButton.disabled = !hasInstance || !hasSchedule;
  improveButton.disabled = !hasInstance || !hasSchedule;
  cpPolishButton.disabled = !hasInstance || !hasSchedule || !byId("focus-term").value;
  exportButton.disabled = !hasInstance || !hasSchedule;
  moveButton.disabled = !hasInstance || !hasSchedule;
  lockButton.disabled = !hasInstance || !hasSchedule;
  unlockButton.disabled = !hasInstance || !hasSchedule;
  saveProjectButton.disabled = !hasInstance;
  undoButton.disabled = !state.history.length;
  redoButton.disabled = !state.redo.length;
  revertButton.disabled = !state.baseSnapshot;
  clearLocksButton.disabled = !hasInstance || !Object.keys(state.instance?.locked_activities || {}).length;
  [
    "conflicts-rescore", "conflicts-improve", "hold-selected", "show-targets",
    "release-held", "why-run", "generator-export-json",
  ].forEach((id) => {
    const button = document.getElementById(id);
    if (button) button.disabled = !hasSchedule;
  });
  byId("release-held").disabled = !state.heldActivityId;
}

function snapshot(label) {
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

function pushHistory(label) {
  if (!state.instance) return;
  state.history.push(snapshot(label));
  state.redo = [];
  if (state.history.length > 50) state.history.shift();
  renderHistory();
}

function restoreSnapshot(snap, status) {
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

function lockCount() {
  return Object.keys(state.instance?.locked_activities || {}).length;
}

function hardConstraintOverrides() {
  return {
    force_repeat_weekly_pattern: byId("repeat-pattern").checked || byId("hard-repeat-week-settings").checked,
    week1_lectures_only: byId("hard-week1").checked,
    enforce_course_totals: byId("hard-course-totals").checked,
    block_profs: byId("hard-block-prof").checked,
    staff_daily_caps: byId("hard-staff-daily").checked,
    staff_weekly_caps: byId("hard-staff-weekly").checked,
    room_availability: byId("hard-room-availability").checked,
    travel_buffers: byId("hard-travel-buffers").checked,
    building_closures: byId("hard-building-closures").checked,
    calendar_rules: byId("hard-calendar-rules").checked,
    precedence_rules: byId("hard-precedence-rules").checked,
  };
}

function applySettingsToSidebar() {
  byId("room-mode").value = byId("settings-room-mode").value;
  byId("profile").value = byId("settings-profile").value;
  byId("time-limit").value = byId("settings-time-limit").value;
  byId("workers").value = byId("settings-workers").value;
  byId("repeat-pattern").checked = byId("hard-repeat-week-settings").checked;
  toast("Settings applied");
}

async function createSession(meta = {}) {
  if (!state.instance) return;
  const payload = await fetchJson("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instance: state.instance, schedule: state.schedule, meta }),
  });
  state.sessionId = String(payload.session_id || "");
  byId("session-id").value = state.sessionId;
  setActionState();
}

async function sessionAction(action, payload = {}) {
  if (!state.sessionId) await createSession();
  if (!state.sessionId) throw new Error("No backend session.");
  const wrapped = await fetchJson(`/sessions/${encodeURIComponent(state.sessionId)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return wrapped.result || wrapped;
}

function entityName(collection, id, fallback) {
  const row = collection[String(id)] || {};
  return String(row.name || row.code || fallback);
}

function populateFilters() {
  if (!state.instance) return;
  const weeks = byId("week-filter");
  weeks.replaceChildren(...state.instance.weeks.map((week) => new Option(`Week ${week}`, String(week))));
  const groups = byId("group-filter");
  groups.replaceChildren(new Option("All groups", ""));
  Object.entries(state.instance.groups).forEach(([id, group]) => groups.add(new Option(String(group.name || `Group ${id}`), id)));
  const days = byId("move-day");
  days.replaceChildren(...state.instance.days.map((day) => new Option(String(day), String(day))));
  byId("why-day").replaceChildren(...state.instance.days.map((day) => new Option(String(day), String(day))));
  byId("why-week").replaceChildren(...state.instance.weeks.map((week) => new Option(`Week ${week}`, String(week))));
  populateHeatmapEntities();
}

function populateActivityControls() {
  const select = byId("activity-select");
  select.replaceChildren();
  if (!state.instance || !Object.keys(state.schedule).length) return;
  Object.entries(state.schedule)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .forEach(([id, info]) => {
      const course = entityName(state.instance.courses, info.course_id, `Course ${info.course_id}`);
      select.add(new Option(`A${id} ${course} W${info.week} ${info.day} S${Number(info.slot) + 1}`, id));
    });
  const whySelect = byId("why-activity");
  whySelect.replaceChildren(...Array.from(select.options).map((option) => new Option(option.text, option.value)));
  syncMoveFieldsFromActivity();
}

function populateHeatmapEntities() {
  if (!state.instance) return;
  const kind = byId("heatmap-kind").value;
  const target = byId("heatmap-entity");
  const collection = kind === "staff" ? state.instance.staff : state.instance.groups;
  target.replaceChildren(...Object.entries(collection).map(([id, row]) => new Option(String(row.name || row.code || id), id)));
}

function syncMoveFieldsFromActivity() {
  const id = byId("activity-select").value;
  const info = state.schedule[String(id)];
  if (!info) return;
  byId("move-day").value = String(info.day);
  byId("move-slot").value = String(info.slot);
  byId("move-room").value = info.room_id == null ? "" : String(info.room_id);
  byId("move-staff").value = info.staff_id == null ? "" : String(info.staff_id);
}

function updateMetrics(status = "Ready") {
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

function updateWorkflowState(status) {
  const hasInstance = Boolean(state.instance);
  const hasSchedule = Boolean(Object.keys(state.schedule || {}).length);
  const conflictCount = Number(state.score.hard_conflict_count ?? state.conflicts.length ?? 0);
  byId("data-state").textContent = hasInstance
    ? `${Object.keys(state.instance.activities).length} activities loaded`
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
  document.querySelectorAll(".step-card[data-step]").forEach((card) => {
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

function renderDiagnostics() {
  renderReadableDiagnostics({
    resultSummary: byId("result-summary"),
    insights: byId("diagnostic-content"),
    penaltyDrivers: byId("penalty-drivers"),
    sideConflicts: byId("conflict-list"),
    resultsConflicts: byId("results-conflict-list"),
    rawDiagnostics: byId("raw-diagnostics"),
  }, state, byId("workers").value);
  renderSimpleConflictList("conflict-review-list");
  renderFairness();
  renderHeatmap();
  renderHistory();
}

function renderSimpleConflictList(targetId) {
  const list = byId(targetId);
  const rows = state.conflicts.length ? state.conflicts : ["None"];
  list.replaceChildren(...rows.map((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }));
}

function renderImprovementProgress(events) {
  const target = byId("improve-progress");
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

function renderHistory() {
  const list = byId("history-list");
  const rows = state.history.length
    ? state.history.slice().reverse().map((snap) => `${snap.at || ""} ${snap.label || "Change"}`.trim())
    : ["No edits yet."];
  list.replaceChildren(...rows.map((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }));
}

function scheduleRows() {
  return Object.entries(state.schedule || {}).map(([id, row]) => ({ id, ...row }));
}

function renderFairness() {
  const rows = scheduleRows();
  const groupLoads = new Map();
  const staffLoads = new Map();
  rows.forEach((event) => {
    (event.group_ids || []).forEach((gid) => groupLoads.set(String(gid), (groupLoads.get(String(gid)) || 0) + 1));
    if (event.staff_id != null) staffLoads.set(String(event.staff_id), (staffLoads.get(String(event.staff_id)) || 0) + 1);
  });
  const makeRows = (loads, collection, fallback) => {
    const values = [...loads.values()];
    const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
    const header = document.createElement("div");
    header.className = "table-like-row header";
    ["Name", "Total slots", "Average", "Difference", "Score"].forEach((text) => {
      const cell = document.createElement("span");
      cell.textContent = text;
      header.append(cell);
    });
    return [header, ...[...loads.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20).map(([id, load]) => {
      const row = document.createElement("div");
      row.className = "table-like-row";
      const diff = load - avg;
      [entityName(collection, id, `${fallback} ${id}`), String(load), String(Math.round(avg * 10) / 10), String(Math.round(diff * 10) / 10), String(Math.abs(Math.round(diff * 10) / 10))].forEach((text) => {
        const cell = document.createElement("span");
        cell.textContent = text;
        row.append(cell);
      });
      return row;
    })];
  };
  byId("fairness-summary").textContent = rows.length
    ? `Computed from ${rows.length} scheduled activities. Lower difference from average is better.`
    : "Load and score a schedule to inspect group and staff fairness.";
  byId("fairness-group-table").replaceChildren(...makeRows(groupLoads, state.instance?.groups || {}, "Group"));
  byId("fairness-staff-table").replaceChildren(...makeRows(staffLoads, state.instance?.staff || {}, "Staff"));
}

function renderHeatmap() {
  const target = byId("heatmap-table");
  const kind = byId("heatmap-kind").value;
  const entity = byId("heatmap-entity").value;
  if (!state.instance || !Object.keys(state.schedule).length || !entity) {
    target.textContent = "Load a schedule and choose an entity.";
    return;
  }
  const counts = new Map();
  state.instance.days.forEach((day) => counts.set(String(day), 0));
  scheduleRows().forEach((event) => {
    const matches = kind === "staff"
      ? String(event.staff_id) === entity
      : (event.group_ids || []).map(String).includes(entity);
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

function moveTargetFor(day, slot) {
  const week = Number(byId("week-filter").value || 0);
  return state.moveTargets.find((target) =>
    Number(target.week) === week &&
    String(target.day) === String(day) &&
    Number(target.slot) === Number(slot)
  );
}

function renderSchedule() {
  const inst = state.instance;
  const table = byId("schedule-table");
  const empty = byId("empty-state");
  if (!inst || !Object.keys(state.schedule).length) {
    table.hidden = true;
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  table.hidden = false;
  const week = Number(byId("week-filter").value || inst.weeks[0]);
  const group = byId("group-filter").value;
  const query = byId("search").value.trim().toLowerCase();
  const head = table.tHead?.rows[0] || table.createTHead().insertRow();
  head.replaceChildren();
  ["Day", ...Array.from({ length: inst.slots_per_day }, (_, index) => `Slot ${index + 1}`)].forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    head.append(th);
  });
  const body = table.tBodies[0] || table.createTBody();
  body.replaceChildren();
  inst.days.forEach((day) => {
    const row = body.insertRow();
    row.insertCell().textContent = day;
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
        const groupIds = event.group_ids || [];
        if (group && !groupIds.map(String).includes(group)) return;
        const course = entityName(inst.courses, event.course_id, `Course ${event.course_id}`);
        const room = entityName(inst.rooms, event.room_id, `Room ${event.room_id}`);
        const staff = entityName(inst.staff, event.staff_id, `Staff ${event.staff_id}`);
        if (query && !`${course} ${room} ${staff} ${activityId}`.toLowerCase().includes(query)) return;
        const card = document.createElement("div");
        card.className = `event ${String(event.kind || "").toLowerCase()}`;
        card.dataset.activityId = activityId;
        if (String(activityId) === String(state.heldActivityId)) card.classList.add("held");
        const title = document.createElement("strong");
        title.textContent = course;
        const detail = document.createElement("span");
        detail.textContent = `${event.kind} · ${staff}`;
        const roomNode = document.createElement("span");
        roomNode.textContent = room;
        card.append(title, detail, roomNode);
        cell.append(card);
      });
    }
  });
}

function acceptInstance(instance) {
  state.instance = instance;
  state.schedule = {};
  state.meta = {};
  state.conflicts = [];
  state.score = {};
  state.sessionId = "";
  state.heldActivityId = "";
  state.moveTargets = [];
  byId("session-id").value = "";
  populateFilters();
  populateActivityControls();
  updateMetrics();
  renderDiagnostics();
  renderSchedule();
}

function acceptSchedule(schedule, meta = {}, score = {}) {
  state.schedule = schedule || {};
  state.meta = meta || {};
  state.score = score || {};
  state.conflicts = score.hard_conflicts || state.conflicts || [];
  state.moveTargets = [];
  updateMetrics(Object.keys(state.schedule).length ? "Schedule loaded" : "No schedule");
  renderDiagnostics();
  renderSchedule();
  populateActivityControls();
  if (!state.baseSnapshot && Object.keys(state.schedule).length) {
    state.baseSnapshot = snapshot("Base schedule");
  }
}

async function loadPreset() {
  const button = byId("load-preset");
  button.disabled = true;
  try {
    const payload = await fetchJson(`/preset/${encodeURIComponent(preset.value)}`);
    acceptInstance(payload.instance);
    await createSession({ source: "preset", mode: preset.value });
    toast(`Loaded ${preset.value}`);
  } catch (error) {
    toast(String(error));
  } finally {
    button.disabled = false;
  }
}

async function solve() {
  if (!state.instance) return;
  solveButton.disabled = true;
  solveButton.textContent = "Solving...";
  updateMetrics("Running");
  try {
    const payload = await sessionAction("solve", { options: solverOptions(), hard_constraints: hardConstraintOverrides() });
    if (Object.keys(state.schedule).length) pushHistory("Before solve");
    state.conflicts = payload.hard_conflicts || [];
    acceptSchedule(payload.schedule || {}, payload.meta || {}, payload.meta?.quality || {});
    updateMetrics(Object.keys(state.schedule).length ? "Feasible" : `Status ${payload.status}`);
  } catch (error) {
    updateMetrics("Failed");
    toast(String(error));
  } finally {
    solveButton.disabled = false;
    solveButton.textContent = "Solve schedule";
  }
}

async function startSolveJob() {
  if (!state.instance) return;
  if (!state.sessionId) await createSession();
  const payload = await fetchJson("/jobs/solve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId, options: solverOptions(), hard_constraints: hardConstraintOverrides() }),
  });
  state.jobId = String(payload.job_id || "");
  byId("job-id").value = state.jobId;
  updateMetrics("Job queued");
}

async function pollJob() {
  if (!state.jobId) return;
  const eventText = await fetch(endpoint(`/jobs/${encodeURIComponent(state.jobId)}/events`)).then((r) => r.text());
  const payload = await fetchJson(`/jobs/${encodeURIComponent(state.jobId)}`);
  state.meta = { ...(state.meta || {}), job: payload, job_event_stream: eventText };
  if (payload.status === "complete" && payload.result?.schedule) {
    const result = payload.result;
    if (Object.keys(state.schedule).length) pushHistory("Before job result");
    acceptSchedule(result.schedule || {}, result.meta || {}, result.meta?.quality || {});
    updateMetrics("Job complete");
  } else {
    updateMetrics(`Job ${payload.status}`);
    renderDiagnostics();
  }
}

async function runPortfolio() {
  if (!state.instance) return;
  portfolioButton.disabled = true;
  portfolioButton.textContent = "Running...";
  try {
    const payload = await sessionAction("portfolio", { options: solverOptions(), hard_constraints: hardConstraintOverrides() });
    const best = (payload.candidates || [])[Number(payload.best_index)];
    if (!best) throw new Error("No feasible portfolio candidate.");
    const result = best.result || {};
    acceptSchedule(result.schedule || {}, result.meta || {}, result.meta?.quality || {});
    toast(`Best profile: ${best.name}`);
  } catch (error) {
    toast(String(error));
  } finally {
    portfolioButton.disabled = false;
    portfolioButton.textContent = "Run portfolio";
  }
}

async function scoreCurrent() {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  const payload = await sessionAction("score");
  state.score = payload;
  state.conflicts = payload.hard_conflicts || [];
  updateMetrics("Scored");
  renderDiagnostics();
}

async function improve() {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  improveButton.disabled = true;
  improveButton.textContent = "Improving...";
  try {
    const payload = await sessionAction("improve", {
      focus_term: byId("focus-term").value,
      options: {
        iterations: Number(byId("improve-iters").value),
        max_seconds: Number(byId("improve-seconds").value) || null,
        progress_every: 10,
      },
    });
    pushHistory("Before improve");
    acceptSchedule(payload.schedule || {}, payload.meta || {}, payload.global_after || payload.after || {});
    renderImprovementProgress(payload.meta?.progress_events || []);
    toast(`Penalty ${payload.before?.soft_penalty ?? "?"} -> ${payload.global_after?.soft_penalty ?? payload.after?.soft_penalty ?? "?"}`);
  } catch (error) {
    toast(String(error));
  } finally {
    improveButton.disabled = false;
    improveButton.textContent = "Improve";
  }
}

async function cpPolish() {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  const focus = byId("focus-term").value;
  if (!focus) {
    toast("Choose a focus term first.");
    return;
  }
  cpPolishButton.disabled = true;
  cpPolishButton.textContent = "Polishing...";
  try {
    const payload = await sessionAction("cp-polish", {
      focus_term: focus,
      affected_limit: 100,
      options: { ...solverOptions(), use_objective: true, objective_profile: "balanced" },
    });
    pushHistory("Before CP polish");
    acceptSchedule(payload.schedule || {}, payload.meta || {}, payload.meta?.quality || {});
    updateMetrics(Object.keys(state.schedule).length ? "Polished" : `Status ${payload.status}`);
  } catch (error) {
    toast(String(error));
  } finally {
    cpPolishButton.disabled = false;
    cpPolishButton.textContent = "Focused CP-SAT polish";
  }
}

async function exportCsv() {
  if (!state.instance || !Object.keys(state.schedule).length) return;
  try {
    const payload = await sessionAction("export-csv", { filename: "planora-schedule.csv" });
    const blob = new Blob([String(payload.content || "")], { type: String(payload.content_type || "text/csv") });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = String(payload.filename || "planora-schedule.csv");
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    toast(String(error));
  }
}

async function moveActivity() {
  const activityId = byId("activity-select").value;
  if (!activityId) return;
  const payload = await sessionAction("move", {
    activity_id: Number(activityId),
    day: byId("move-day").value,
    slot: Number(byId("move-slot").value),
    room_id: Number(byId("move-room").value),
    staff_id: Number(byId("move-staff").value),
    enforce_hard_conflict_free: !byId("allow-conflict-move").checked,
  });
  pushHistory("Before move");
  acceptSchedule(payload.schedule || state.schedule, state.meta, payload.score || {});
  toast(payload.ok ? "Moved activity" : "Move blocked by hard conflicts");
}

async function loadMoveTargets() {
  const activityId = state.heldActivityId || byId("activity-select").value;
  if (!activityId || !state.instance || !Object.keys(state.schedule).length) return;
  const current = state.schedule[String(activityId)] || {};
  const payload = await sessionAction("move-deltas", {
    activity_id: Number(activityId),
    week: Number(byId("week-filter").value || current.week),
    room_id: current.room_id,
    staff_id: current.staff_id,
  });
  state.heldActivityId = String(activityId);
  state.moveTargets = payload.targets || [];
  const viable = state.moveTargets.filter((target) => target.ok).length;
  byId("hold-status").textContent = `Holding A${activityId}. ${viable}/${state.moveTargets.length} visible targets are viable; negative deltas improve the score.`;
  setActionState();
  renderSchedule();
}

async function moveHeldToTarget(day, slot) {
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
  acceptSchedule(payload.schedule || state.schedule, state.meta, payload.score || {});
  state.heldActivityId = "";
  state.moveTargets = [];
  byId("hold-status").textContent = payload.ok ? "Activity moved. Hold another activity to preview new targets." : "Move was blocked by hard conflicts.";
  setActionState();
}

async function lockActivity() {
  const activityId = byId("activity-select").value;
  if (!activityId) return;
  const payload = await sessionAction("lock", { activity_id: Number(activityId), fields: ["day", "slot", "room_id"] });
  pushHistory("Before lock");
  state.instance = payload.instance;
  toast("Activity locked");
  setActionState();
}

async function unlockActivity() {
  const activityId = byId("activity-select").value;
  if (!activityId) return;
  const payload = await sessionAction("unlock", { activity_id: Number(activityId) });
  pushHistory("Before unlock");
  state.instance = payload.instance;
  toast("Activity unlocked");
  setActionState();
}

async function clearLocks() {
  if (!state.instance) return;
  pushHistory("Before clear locks");
  const payload = await sessionAction("unlock", {});
  state.instance = payload.instance;
  toast(`Cleared locks (${lockCount()} remaining)`);
  setActionState();
  renderDiagnostics();
}

function undo() {
  const snap = state.history.pop();
  if (!snap) return;
  state.redo.push(snapshot("Redo point"));
  restoreSnapshot(snap, "Undo");
}

function redo() {
  const snap = state.redo.pop();
  if (!snap) return;
  state.history.push(snapshot("Undo point"));
  restoreSnapshot(snap, "Redo");
}

function revertBase() {
  if (!state.baseSnapshot) return;
  pushHistory("Before revert base");
  restoreSnapshot(state.baseSnapshot, "Reverted");
}

function explainWhySlot() {
  const activityId = byId("why-activity").value;
  if (!activityId) return;
  const event = state.schedule[String(activityId)];
  const day = byId("why-day").value;
  const slot = Number(byId("why-slot").value);
  const blockers = scheduleRows().filter((other) => {
    if (String(other.id) === String(activityId)) return false;
    if (Number(other.week) !== Number(byId("why-week").value)) return false;
    if (String(other.day) !== day || Number(other.slot) !== slot) return false;
    const sameStaff = event?.staff_id != null && String(other.staff_id) === String(event.staff_id);
    const sameRoom = event?.room_id != null && String(other.room_id) === String(event.room_id);
    const groups = new Set((event?.group_ids || []).map(String));
    const sameGroup = (other.group_ids || []).some((gid) => groups.has(String(gid)));
    return sameStaff || sameRoom || sameGroup;
  });
  byId("why-output").textContent = blockers.length
    ? `Blocked by ${blockers.length} activity/activities at that slot:\n` + blockers.slice(0, 12).map((row) => `- A${row.id} ${entityName(state.instance?.courses || {}, row.course_id, `Course ${row.course_id}`)}`).join("\n")
    : "No direct staff, room, or group overlap found for that candidate slot.";
}

function exportInstanceJson() {
  if (!state.instance) return;
  const blob = new Blob([JSON.stringify(state.instance, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "planora-instance.json";
  link.click();
  URL.revokeObjectURL(url);
}

async function refreshProjects() {
  const select = byId("project-select");
  try {
    const payload = await fetchJson("/projects");
    select.replaceChildren(...(payload.projects || []).map((row) => new Option(String(row.name), String(row.name))));
  } catch (_error) {
    select.replaceChildren();
  }
}

async function saveProject() {
  if (!state.instance) return;
  const name = byId("project-name").value || "web-project";
  await fetchJson("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, session_id: state.sessionId, instance: state.instance, schedule: state.schedule, meta: state.meta }),
  });
  await refreshProjects();
  toast(`Saved ${name}`);
}

async function loadProject() {
  const name = byId("project-select").value;
  if (!name) return;
  const payload = await fetchJson(`/projects/${encodeURIComponent(name)}`);
  acceptInstance(payload.instance);
  acceptSchedule(payload.schedule || {}, payload.meta || {}, {});
  await createSession({ source: "project", name });
  toast(`Loaded ${name}`);
}

byId("load-preset").addEventListener("click", loadPreset);
solveButton.addEventListener("click", solve);
solveJobButton.addEventListener("click", () => { startSolveJob().catch((error) => toast(String(error))); });
pollJobButton.addEventListener("click", () => { pollJob().catch((error) => toast(String(error))); });
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
  state.heldActivityId = byId("activity-select").value;
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
  const cell = target.closest("td[data-day][data-slot]");
  if (!cell || !state.heldActivityId) return;
  moveHeldToTarget(String(cell.dataset.day), Number(cell.dataset.slot)).catch((error) => toast(String(error)));
});
byId("why-run").addEventListener("click", explainWhySlot);
byId("heatmap-kind").addEventListener("change", () => { populateHeatmapEntities(); renderHeatmap(); });
byId("heatmap-entity").addEventListener("change", renderHeatmap);
byId("heatmap-metric").addEventListener("change", renderHeatmap);
byId("generator-load-current").addEventListener("click", () => {
  if (!state.instance) return;
  byId("gen-programs").value = String(Object.keys(state.instance.programs || {}).length || 0);
  byId("gen-groups").value = String(Object.keys(state.instance.groups || {}).length || 0);
  byId("gen-courses").value = String(Object.keys(state.instance.courses || {}).length || 0);
  byId("gen-staff").value = String(Object.keys(state.instance.staff || {}).length || 0);
  byId("gen-rooms").value = String(Object.keys(state.instance.rooms || {}).length || 0);
});
byId("generator-export-json").addEventListener("click", exportInstanceJson);
apiUrl.addEventListener("change", refreshApi);
byId("instance-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    acceptInstance(JSON.parse(await file.text()));
    await createSession({ source: "instance_json", filename: file.name });
    toast(`Loaded ${file.name}`);
  } catch (error) {
    toast(`Invalid instance JSON: ${error}`);
  }
});
byId("csv-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const payload = await fetchJson("/import/csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content: await file.text(),
        lock_imported: byId("lock-imported").checked,
      }),
    });
    state.instance = payload.instance;
    populateFilters();
    acceptSchedule(payload.schedule || {}, payload.meta || {}, payload.score || {});
    await createSession({ source: "timetable_csv", filename: file.name });
    toast(`Imported ${file.name}`);
  } catch (error) {
    toast(`CSV import failed: ${error}`);
  }
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
