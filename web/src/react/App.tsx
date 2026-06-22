import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { createApiClient, DEFAULT_PRINCIPAL } from "./api";
import { AccountPanel } from "./components/AccountPanel";
import { AdminPanel } from "./components/AdminPanel";
import { AccessPanel } from "./components/AccessPanel";
import { AppShell } from "./components/AppShell";
import { LoginPanel } from "./components/LoginPanel";
import { OperationsPanel, RunSummary } from "./components/OperationsPanel";
import { ParityPanel } from "./components/ParityPanel";
import { ProjectsPanel } from "./components/ProjectsPanel";
import { ReviewPanel } from "./components/ReviewPanel";
import { ScheduleBoard } from "./components/ScheduleBoard";
import { SettingsPanel } from "./components/SettingsPanel";
import type { Dict, Instance, OrganizationMembership, Principal, Schedule, ViewKey } from "./types";

const API_DEFAULT = import.meta.env.VITE_PLANORA_API_URL || "http://127.0.0.1:8787";

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

const DEFAULT_SETTINGS: SolverSettings = {
  roomMode: "greedy",
  profile: "university_fast",
  timeLimitSeconds: 60,
  workers: 4,
  useObjective: false,
  forceRepeatWeeklyPattern: false,
  improveIterations: 1000,
  improveSeconds: 10,
  progressEvery: 10,
};

const VIEW_PATHS: Record<ViewKey, string> = {
  home: "/",
  faq: "/faq",
  login: "/login",
  account: "/account",
  workspace: "/workspace",
  operations: "/runs",
  review: "/diagnostics",
  settings: "/settings",
  fairness: "/insights",
  projects: "/projects",
  parity: "/platform",
  access: "/access",
  admin: "/admin",
};

const PATH_VIEWS: Record<string, ViewKey> = Object.fromEntries(
  Object.entries(VIEW_PATHS).map(([key, path]) => [path, key as ViewKey]),
) as Record<string, ViewKey>;

function viewFromLocation(): ViewKey {
  return PATH_VIEWS[window.location.pathname] || "workspace";
}

type Toast = {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
};

type ThemeMode = "light" | "dark";
type AnalyticsConsent = "pending" | "granted" | "denied";

function readStoredTheme(): ThemeMode {
  const stored = localStorage.getItem("planora_theme");
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readAnalyticsConsent(): AnalyticsConsent {
  const stored = localStorage.getItem("planora_analytics_consent");
  return stored === "granted" || stored === "denied" ? stored : "pending";
}

function setCookie(name: string, value: string, maxAgeSeconds: number) {
  document.cookie = `${name}=${encodeURIComponent(value)}; Max-Age=${maxAgeSeconds}; Path=/; SameSite=Lax`;
}

function clearCookie(name: string) {
  document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
}

function analyticsClientId(): string {
  const existing = localStorage.getItem("planora_analytics_id");
  if (existing) return existing;
  const next = crypto.randomUUID();
  localStorage.setItem("planora_analytics_id", next);
  setCookie("planora_analytics", next, 60 * 60 * 24 * 365);
  return next;
}

export function App() {
  const [principal, setPrincipal] = useState<Principal>(DEFAULT_PRINCIPAL);
  const [token, setToken] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [view, setView] = useState<ViewKey>(viewFromLocation);
  const [presets, setPresets] = useState<string[]>([]);
  const [authConfig, setAuthConfig] = useState<Dict>({});
  const [credentials, setCredentials] = useState({ email: "", password: "", displayName: "", inviteCode: "", verificationCode: "" });
  const [accessSnapshot, setAccessSnapshot] = useState<Dict>({});
  const [organizations, setOrganizations] = useState<OrganizationMembership[]>([]);
  const [instance, setInstance] = useState<Instance | null>(null);
  const [schedule, setSchedule] = useState<Schedule>({});
  const [sessionId, setSessionId] = useState("");
  const [score, setScore] = useState<Dict>({});
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [projects, setProjects] = useState<Dict[]>([]);
  const [auditEvents, setAuditEvents] = useState<Dict[]>([]);
  const [parity, setParity] = useState<Dict>({});
  const [system, setSystem] = useState<Dict>({});
  const [analyticsSummary, setAnalyticsSummary] = useState<Dict>({});
  const [selectedActivityId, setSelectedActivityId] = useState("");
  const [heldActivityId, setHeldActivityId] = useState("");
  const [moveTargets, setMoveTargets] = useState<Dict[]>([]);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [theme, setTheme] = useState<ThemeMode>(readStoredTheme);
  const [analyticsConsent, setAnalyticsConsent] = useState<AnalyticsConsent>(readAnalyticsConsent);

  const api = useMemo(() => createApiClient(API_DEFAULT, principal, token), [principal, token]);

  const trackAnalytics = useCallback((eventName: string, details: Dict = {}) => {
    if (analyticsConsent !== "granted") return;
    const payload = {
      client_id: analyticsClientId(),
      event_name: eventName,
      path: window.location.pathname,
      view_name: view,
      referrer: document.referrer || "",
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      tenant_id: authenticated ? principal.tenant_id : "public",
      user_role: authenticated ? principal.role : "anonymous",
      details,
    };
    const target = `${API_DEFAULT.replace(/\/$/, "")}/analytics/event`;
    const body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      const sent = navigator.sendBeacon(target, new Blob([body], { type: "application/json" }));
      if (sent) return;
    }
    fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
      credentials: "include",
    }).catch(() => undefined);
  }, [analyticsConsent, authenticated, principal.role, principal.tenant_id, view]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("planora_theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("planora_analytics_consent", analyticsConsent);
    if (analyticsConsent === "granted") {
      const id = analyticsClientId();
      setCookie("planora_analytics", id, 60 * 60 * 24 * 365);
    } else if (analyticsConsent === "denied") {
      clearCookie("planora_analytics");
      localStorage.removeItem("planora_analytics_id");
    }
  }, [analyticsConsent]);

  useEffect(() => {
    trackAnalytics("page_view");
  }, [view, trackAnalytics]);

  function notify(message: string, kind: Toast["kind"] = "info") {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current.slice(-3), { id, kind, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5200);
  }

  const refreshBootstrap = useCallback(async () => {
    const authPayload = await api.get<Dict>("/auth/config");
    setAuthConfig(authPayload);
    const whoami = await api.get<Principal>("/auth/whoami");
    const [presetPayload, projectPayload, parityPayload] = await Promise.all([
      api.get<{ presets: string[] }>("/presets"),
      api.get<{ projects: Dict[] }>("/projects"),
      api.get<Dict>("/parity"),
    ]);
    const organizationPayload = await api.get<{ organizations: OrganizationMembership[] }>("/access/my-organizations");
    setPrincipal(whoami);
    setAuthenticated(true);
    setPresets(presetPayload.presets || []);
    setProjects(projectPayload.projects || []);
    setParity(parityPayload);
    setOrganizations(organizationPayload.organizations || []);
    if (whoami.permissions.includes("audit:read")) {
      const requests: [Promise<{ events: Dict[] }>, Promise<Dict>, Promise<Dict>] = [
        api.get<{ events: Dict[] }>("/audit"),
        api.get<Dict>("/system"),
        api.get<Dict>("/analytics/summary"),
      ];
      const [audit, systemPayload, analyticsPayload] = await Promise.all(requests);
      setAuditEvents(audit.events || []);
      setSystem(systemPayload);
      setAnalyticsSummary(analyticsPayload);
    } else {
      setAuditEvents([]);
      setSystem({});
      setAnalyticsSummary({});
    }
    if (whoami.permissions.includes("access:manage")) {
      setAccessSnapshot(await api.get<Dict>("/access"));
    } else {
      setAccessSnapshot({});
    }
  }, [api]);

  useEffect(() => {
    refreshBootstrap().catch((error: unknown) => {
      setAuthenticated(false);
      notify(String(error).includes("Authentication required") ? "Sign in or create an account to continue." : String(error), "info");
      if (!["/", "/login", "/faq"].includes(window.location.pathname)) {
        window.history.replaceState(null, "", "/login");
        setView("login");
      }
      api.get<Dict>("/auth/config").then(setAuthConfig).catch(() => undefined);
    });
  }, [refreshBootstrap]);

  useEffect(() => {
    const onPop = () => setView(viewFromLocation());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function navigate(nextView: ViewKey) {
    setView(nextView);
    const path = VIEW_PATHS[nextView] || "/workspace";
    if (window.location.pathname !== path) {
      window.history.pushState(null, "", path);
    }
  }

  function signOut() {
    trackAnalytics("logout");
    setToken("");
    setAuthenticated(false);
    setPrincipal(DEFAULT_PRINCIPAL);
    setInstance(null);
    setSchedule({});
    setSessionId("");
    setOrganizations([]);
    notify("Signed out", "info");
    window.history.pushState(null, "", "/login");
    setView("login");
  }

  async function ensureSession(nextInstance = instance, nextSchedule = schedule): Promise<string> {
    if (sessionId) return sessionId;
    if (!nextInstance) throw new Error("Load an instance first.");
    const payload = await api.post<{ session_id: string }>("/sessions", {
      instance: nextInstance,
      schedule: nextSchedule,
      meta: { source: "react-web" },
    });
    setSessionId(String(payload.session_id || ""));
    return String(payload.session_id || "");
  }

  async function loadPreset(mode: string) {
    setBusy(true);
    try {
      const payload = await api.get<{ instance: Instance }>(`/preset/${encodeURIComponent(mode)}`);
      setInstance(payload.instance);
      setSchedule({});
      setScore({});
      setConflicts([]);
      setSessionId("");
      setSelectedActivityId("");
      setHeldActivityId("");
      setMoveTargets([]);
      setSelectedWeek(Number(payload.instance.weeks?.[0] || 1));
      trackAnalytics("preset_loaded", { mode });
      notify(`Loaded ${mode}`, "success");
      navigate("workspace");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function login() {
    const payload = await api.post<{ token: string; principal: Principal }>("/auth/login", {
      email: credentials.email,
      password: credentials.password,
    });
    setToken(payload.token);
    setPrincipal(payload.principal);
    setAuthenticated(true);
    trackAnalytics("login_success", { role: payload.principal.role, tenant_id: payload.principal.tenant_id });
    notify("Signed in", "success");
    navigate("workspace");
  }

  async function register() {
    const payload = await api.post<Dict>("/auth/register", {
      email: credentials.email,
      password: credentials.password,
      display_name: credentials.displayName,
    });
    const verificationUrl = payload.verification_url ? ` Dev verification link: ${String(payload.verification_url)}` : "";
    notify(`Registration created. Check your email to confirm the account.${verificationUrl}`, "success");
  }

  async function verifyEmail() {
    await api.post<Dict>("/auth/verify", { token: credentials.verificationCode });
    notify("Email confirmed. You can sign in now.", "success");
  }

  async function applyAccessChange(change: Dict) {
    const next = await api.post<Dict>("/access", change);
    setAccessSnapshot(next);
    notify("Access settings updated", "success");
  }

  async function joinInvite(code: string) {
    const payload = await api.post<{ principal: Principal; organizations: OrganizationMembership[] }>("/access/join-invite", { invite_code: code });
    setPrincipal(payload.principal);
    setOrganizations(payload.organizations || []);
    trackAnalytics("invite_joined", { tenant_id: payload.principal.tenant_id, role: payload.principal.role });
    notify("Group joined. Your active organization and permissions have been refreshed.", "success");
  }

  async function switchOrganization(tenantId: string) {
    const payload = await api.post<{ principal: Principal; organizations: OrganizationMembership[] }>("/access/switch-organization", { tenant_id: tenantId });
    setPrincipal(payload.principal);
    setOrganizations(payload.organizations || []);
    setInstance(null);
    setSchedule({});
    setSessionId("");
    setScore({});
    setConflicts([]);
    trackAnalytics("organization_switched", { tenant_id: payload.principal.tenant_id });
    notify(`Switched to ${payload.principal.tenant_id}`, "success");
  }

  async function solve() {
    if (!instance) return;
    setBusy(true);
    try {
      const sid = await ensureSession(instance, schedule);
      const payload = await api.post<Dict>(`/sessions/${sid}/solve`, {
        options: {
          room_mode: settings.roomMode,
          use_objective: settings.useObjective,
          retry_without_objective: true,
          objective_profile: settings.profile,
          time_limit_seconds: settings.timeLimitSeconds,
          workers: settings.workers,
          force_repeat_weekly_pattern: settings.forceRepeatWeeklyPattern,
        },
      });
      const result = payload.result as Dict;
      setSchedule((result.schedule || {}) as Schedule);
      const hardConflicts = Array.isArray(result.hard_conflicts) ? result.hard_conflicts : [];
      setConflicts(hardConflicts as string[]);
      setScore(((result.meta as Dict)?.quality || {}) as Dict);
      trackAnalytics("solve_complete", { status: result.status, hard_conflicts: hardConflicts.length });
      notify("Solve complete", "success");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function scoreCurrent() {
    setBusy(true);
    try {
      const sid = await ensureSession(instance, schedule);
      const payload = await api.post<Dict>(`/sessions/${sid}/score`, {});
      const result = payload.result as Dict;
      setScore(result);
      const hardConflicts = Array.isArray(result.hard_conflicts) ? result.hard_conflicts : [];
      setConflicts(hardConflicts as string[]);
      trackAnalytics("score_recalculated", { hard_conflicts: hardConflicts.length });
      notify("Score recalculated", "success");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function improve() {
    setBusy(true);
    try {
      const sid = await ensureSession(instance, schedule);
      const payload = await api.post<Dict>(`/sessions/${sid}/improve`, {
        options: {
          iterations: settings.improveIterations,
          max_seconds: settings.improveSeconds,
          progress_every: settings.progressEvery,
        },
      });
      const result = payload.result as Dict;
      setSchedule((result.schedule || {}) as Schedule);
      setScore((result.global_after || result.after || {}) as Dict);
      trackAnalytics("improve_complete", { iterations: settings.improveIterations, seconds: settings.improveSeconds });
      notify("Improve complete", "success");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function startImproveJob() {
    const sid = await ensureSession(instance, schedule);
    const payload = await api.post<Dict>("/jobs/improve", {
      session_id: sid,
      options: {
        iterations: settings.improveIterations,
        max_seconds: settings.improveSeconds,
        progress_every: settings.progressEvery,
      },
    });
    trackAnalytics("improve_job_started", { job_id: payload.job_id, iterations: settings.improveIterations });
    notify(`Background improve job ${String(payload.job_id || "")} started`, "success");
  }

  async function holdSelected() {
    if (!selectedActivityId) return;
    const sid = await ensureSession(instance, schedule);
    const payload = await api.post<Dict>(`/sessions/${sid}/move-deltas`, {
      activity_id: Number(selectedActivityId),
      week: selectedWeek,
      limit: 60,
    });
    const result = payload.result as Dict;
    setHeldActivityId(selectedActivityId);
    setMoveTargets((result.targets || []) as Dict[]);
    notify(`Previewing move targets for A${selectedActivityId}`, "info");
  }

  async function moveTarget(day: string, slot: number) {
    if (!heldActivityId) return;
    const sid = await ensureSession(instance, schedule);
    const target = moveTargets.find((row: Dict) => String(row.day) === day && Number(row.slot) === slot);
    if (!target?.ok) return;
    const payload = await api.post<Dict>(`/sessions/${sid}/move`, {
      activity_id: Number(heldActivityId),
      week: target.week,
      day,
      slot,
      room_id: target.room_id,
      staff_id: target.staff_id,
      enforce_hard_conflict_free: true,
    });
    const result = payload.result as Dict;
    setSchedule((result.schedule || schedule) as Schedule);
    setScore((result.score || {}) as Dict);
    setHeldActivityId("");
    setMoveTargets([]);
    notify("Moved activity", "success");
  }

  const homeContent = (
    <div className="public-home">
      <section className="home-hero">
        <div className="welcome-copy">
          <h1>Explainable scheduling for real university constraints.</h1>
          <p>
            Planora imports timetable data, detects hard conflicts, scores schedule quality, and shows repair choices clearly for students, lecturers, TAs, and administrators.
          </p>
          <div className="hero-stats" aria-label="Planora summary metrics">
            <span><strong>16</strong> conflict types surfaced</span>
            <span><strong>10x</strong> penalty reductions on tuned runs</span>
            <span><strong>Roles</strong> filtered by organization</span>
          </div>
        </div>
        <div
          className="schedule-demo"
          role="img"
          aria-label="Animated one-week repair simulation showing a high-penalty schedule with conflicts becoming a cleaner schedule after two improvement runs."
        >
          <div className="demo-head">
            <span>One-week repair simulation</span>
            <div className="demo-score">
              <strong>14552</strong>
              <i />
              <strong>1508</strong>
            </div>
          </div>
          <div className="demo-stage">
            <div className="demo-grid-lines" />
            {[
              {
                label: "Run 0",
                penalty: "14552",
                note: "16 conflicts",
                status: "conflict",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["clash conflict", "TUE", "11:00", "A50/A51 room clash", 2, 2, 2],
                  ["lec", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 1",
                penalty: "8820",
                note: "9 conflicts",
                status: "repairing",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["clash conflict", "TUE", "11:00", "A51 clash", 2, 2, 1],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["lec", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 2",
                penalty: "4210",
                note: "3 conflicts",
                status: "repairing",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["tut", "TUE", "13:00", "A51 Tutorial", 2, 3, 1],
                  ["lec", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 3",
                penalty: "2360",
                note: "1 conflict",
                status: "repairing",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["tut shifted", "FRI", "11:00", "A51 Tutorial", 5, 2, 1],
                  ["lec same", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 4",
                penalty: "1508",
                note: "clean",
                status: "clean",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["tut shifted", "FRI", "11:00", "A51 Tutorial", 4, 1, 2],
                  ["lec same", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
            ].map((run, runIndex) => (
              <div key={run.label} className={`demo-run run-${runIndex}`}>
                <div className="run-label">
                  <strong>{run.label}</strong>
                  <span>{run.note}</span>
                </div>
                <div className={`run-status ${run.status}`}>{run.penalty}</div>
                {run.blocks.map(([kind, day, time, label, column, row, span]) => (
                  <span
                    key={`${run.label}-${label}`}
                    className={`demo-block ${kind}`}
                    style={{
                      gridColumn: `${column} / span ${span}`,
                      gridRow: `${Number(row) + 1}`,
                    }}
                  >
                    <b>{label}</b>
                    <small>{day} {time}</small>
                  </span>
                ))}
              </div>
            ))}
          </div>
          <div className="demo-days">
            {["MON", "TUE", "WED", "THU", "FRI"].map((day) => <span key={day}>{day}</span>)}
          </div>
        </div>
      </section>

      <section className="public-section">
        <div className="section-title">
          <h2>See conflicts, quality, and repair options clearly</h2>
          <p>Planora turns raw timetable data into explainable dashboards: conflict lists, penalty drivers, local-search improvements, and role-filtered schedule views.</p>
        </div>
        <div className="visual-grid" aria-label="Planora capabilities">
          <article>
            <strong>Hard conflict visibility</strong>
            <div className="bar-chart"><span style={{ height: "70%" }} /><span style={{ height: "38%" }} /><span style={{ height: "12%" }} /></div>
            <p>Room, staff, and group overlaps are surfaced before admins publish changes.</p>
          </article>
          <article>
            <strong>Penalty driver breakdown</strong>
            <div className="donut-chart" />
            <p>Quality terms explain why a timetable score is high and where to focus improvement.</p>
          </article>
          <article>
            <strong>Move previews</strong>
            <div className="target-grid"><span /><span className="ok" /><span /><span className="warn" /><span className="ok" /><span /></div>
            <p>Admins can hold an activity and see viable target cells with score deltas.</p>
          </article>
        </div>
      </section>
    </div>
  );

  const loginContent = (
    <div className="auth-page">
      <LoginPanel
        principal={principal}
        authConfig={authConfig}
        credentials={credentials}
        onLogin={() => login().catch((error: unknown) => notify(String(error), "error"))}
        onRegister={() => register().catch((error: unknown) => notify(String(error), "error"))}
        onVerify={() => verifyEmail().catch((error: unknown) => notify(String(error), "error"))}
        onCredentialsChange={setCredentials}
      />
    </div>
  );

  const faqContent = (
    <div className="faq-page">
      <section className="panel faq-hero">
        <h1>FAQ</h1>
        <p>Short answers for students, professors, TAs, and university admins using Planora.</p>
      </section>
      <section className="faq-grid">
        {[
          ["What is Planora?", "A timetable planning system that combines imports, CP-SAT solving, local search improvement, conflict diagnostics, and role-based schedule viewing."],
          ["Who can use it?", "Students can view their group schedule, professors and TAs can view assignments, university admins can solve and repair schedules, and global admins can manage all tenants."],
          ["What are invite codes?", "Invite codes are used after account creation. They let a signed-in user join a university group and receive the schedule visibility or editing permissions assigned to that group."],
          ["Can one user join multiple organizations?", "Yes. Use My Groups after login to redeem invite codes for different universities, then switch the active organization from the account page."],
          ["Do you use analytics cookies?", "Analytics is optional. Essential cookies support login, CSRF protection, and consent. First-party analytics cookies are only set if you opt in."],
          ["Where is the data stored?", "The production Docker deployment stores SQLite data in the planora-data volume.."],
        ].map(([question, answer]) => (
          <article className="faq-card" key={question}>
            <h2>{question}</h2>
            <p>{answer}</p>
          </article>
        ))}
      </section>
    </div>
  );

  const workspaceContent = (
    <div className="stack">
      <section className="panel workspace-hero">
        <div className="panel-heading">
          <div>
            <h2>Workspace</h2>
            <p className="section-copy">
              This page is the operational surface for schedulers and university admins: authenticate, load data, solve, improve, and repair directly on the board.
            </p>
          </div>
        </div>
        <div className="hero-metrics">
          <div className="hero-chip">
            <span>Tenant</span>
            <strong>{principal.tenant_id}</strong>
          </div>
          <div className="hero-chip">
            <span>Role</span>
            <strong>{principal.role}</strong>
          </div>
          <div className="hero-chip">
            <span>Activities</span>
            <strong>{instance ? Object.keys(instance.activities || {}).length : 0}</strong>
          </div>
          <div className="hero-chip">
            <span>Displayed week</span>
            <strong>{selectedWeek}</strong>
          </div>
        </div>
      </section>

      <ScheduleBoard
        instance={instance}
        schedule={schedule}
        selectedWeek={selectedWeek}
        targets={moveTargets}
        heldActivityId={heldActivityId}
        selectedActivityId={selectedActivityId}
        onWeekChange={setSelectedWeek}
        onSelectActivity={setSelectedActivityId}
        onHold={() => holdSelected().catch((error: unknown) => notify(String(error), "error"))}
        onRelease={() => {
          setHeldActivityId("");
          setMoveTargets([]);
          notify("Hold released", "info");
        }}
        onMoveTarget={(day, slot) => moveTarget(day, slot).catch((error: unknown) => notify(String(error), "error"))}
      />
    </div>
  );

  const content = {
    home: homeContent,
    faq: faqContent,
    login: loginContent,
    account: (
      <AccountPanel
        principal={principal}
        organizations={organizations}
        onJoinInvite={joinInvite}
        onSwitchOrganization={switchOrganization}
      />
    ),
    workspace: workspaceContent,
    review: <ReviewPanel conflicts={conflicts} score={score} />,
    operations: (
      <div className="solve-page">
        <aside className="solve-sidebar">
          <strong>Solve workflow</strong>
          <a href="#load">1. Load scenario</a>
          <a href="#solve">2. Build schedule</a>
          <a href="#improve">3. Improve quality</a>
          <a href="#score">4. Analyze result</a>
          <button type="button" onClick={() => navigate("settings")}>Solver settings</button>
        </aside>
        <div className="stack">
          <OperationsPanel
            instance={instance}
            presets={presets}
            busy={busy}
            settings={settings}
            onLoadPreset={loadPreset}
            onSolve={solve}
            onImprove={improve}
            onScore={scoreCurrent}
            onStartImproveJob={() => startImproveJob().catch((error: unknown) => notify(String(error), "error"))}
          />
          <RunSummary score={score} conflicts={conflicts} />
        </div>
      </div>
    ),
    settings: <SettingsPanel settings={settings} onChange={setSettings} />,
    fairness: (
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Insights</h2>
            <p className="section-copy">
              Use Diagnostics to inspect current penalty drivers. This area is reserved for richer fairness tables and cross-week load summaries.
            </p>
          </div>
        </div>
      </section>
    ),
    projects: <ProjectsPanel projects={projects} onRefresh={() => refreshBootstrap().catch((error: unknown) => notify(String(error), "error"))} />,
    parity: <ParityPanel manifest={parity} />,
    access: <AccessPanel principal={principal} snapshot={accessSnapshot} onChange={applyAccessChange} />,
    admin: <AdminPanel principal={principal} auditEvents={auditEvents} system={system} analytics={analyticsSummary} />,
  } as Record<ViewKey, ReactNode>;

  return (
    <AppShell
      principal={principal}
      activeView={view}
      authenticated={authenticated}
      theme={theme}
      analyticsConsent={analyticsConsent}
      onViewChange={navigate}
      onSignOut={signOut}
      onThemeToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
      onAnalyticsConsentChange={setAnalyticsConsent}
    >
      {content[view]}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.kind}`}>
            {toast.message}
          </div>
        ))}
      </div>
      {analyticsConsent === "pending" ? (
        <div className="cookie-banner" role="dialog" aria-label="Cookie notice">
          <div>
            <strong>Cookie settings</strong>
            <p>Planora uses essential cookies for login, CSRF protection, and consent. Optional first-party analytics helps improve the product and can be turned off anytime.</p>
          </div>
          <div className="cookie-actions">
            <button type="button" className="secondary-button" onClick={() => setAnalyticsConsent("denied")}>
              Essential only
            </button>
            <button type="button" onClick={() => setAnalyticsConsent("granted")}>
              Allow analytics
            </button>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
