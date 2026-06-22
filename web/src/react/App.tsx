import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, createApiClient, DEFAULT_PRINCIPAL } from "./api";
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
  privacy: "/privacy",
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
type LoginInitialMode = "login" | "register" | "verify" | "forgot" | "reset";

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
  const [credentials, setCredentials] = useState({
    email: "",
    password: "",
    newPassword: "",
    displayName: "",
    inviteCode: "",
    verificationCode: "",
    resetCode: "",
    resetToken: "",
  });
  const [accessSnapshot, setAccessSnapshot] = useState<Dict>({});
  const [organizations, setOrganizations] = useState<OrganizationMembership[]>([]);
  const [authSessions, setAuthSessions] = useState<Dict[]>([]);
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
  const [jobStatus, setJobStatus] = useState<Dict | null>(null);
  const [selectedActivityId, setSelectedActivityId] = useState("");
  const [heldActivityId, setHeldActivityId] = useState("");
  const [moveTargets, setMoveTargets] = useState<Dict[]>([]);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [theme, setTheme] = useState<ThemeMode>(readStoredTheme);
  const [analyticsConsent, setAnalyticsConsent] = useState<AnalyticsConsent>(readAnalyticsConsent);
  const [verificationSuccess, setVerificationSuccess] = useState(false);
  const [redirectSeconds, setRedirectSeconds] = useState(5);
  const [loginInitialMode, setLoginInitialMode] = useState<LoginInitialMode>("login");
  const bootstrapStarted = useRef(false);

  const api = useMemo(
    () => createApiClient(API_DEFAULT, principal, token),
    [principal.user_id, principal.role, principal.tenant_id, token],
  );

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
    const target = `${API_DEFAULT.replace(/\/$/, "")}/events/collect`;
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
    const sessionPayload = await api.get<{ sessions: Dict[] }>("/auth/sessions");
    setPrincipal(whoami);
    setAuthenticated(true);
    setPresets(presetPayload.presets || []);
    setProjects(projectPayload.projects || []);
    setParity(parityPayload);
    setOrganizations(organizationPayload.organizations || []);
    setAuthSessions(sessionPayload.sessions || []);
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
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    refreshBootstrap().catch((error: unknown) => {
      const authenticationFailure = error instanceof ApiError && [401, 403].includes(error.status);
      if (authenticationFailure) {
        setAuthenticated(false);
        notify("Sign in or create an account to continue.", "info");
        if (!["/", "/login", "/faq", "/privacy"].includes(window.location.pathname)) {
          window.history.replaceState(null, "", "/login");
          setView("login");
        }
      } else if (error instanceof ApiError && error.status === 429) {
        const wait = error.retryAfter ? ` Try again in ${error.retryAfter} seconds.` : " Try again shortly.";
        notify(`The server is temporarily busy.${wait}`, "error");
      } else {
        notify(String(error), "error");
      }
    });
  }, [refreshBootstrap]);

  useEffect(() => {
    const onPop = () => setView(viewFromLocation());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("verified") === "1") {
      setVerificationSuccess(true);
      setRedirectSeconds(5);
      setLoginInitialMode("login");
      setView("login");
      return;
    }
    const resetToken = params.get("reset_token");
    if (resetToken) {
      setCredentials((current) => ({ ...current, resetToken }));
      setLoginInitialMode("reset");
      setView("login");
    }
  }, []);

  useEffect(() => {
    if (!verificationSuccess) return undefined;
    setRedirectSeconds(5);
    const interval = window.setInterval(() => {
      setRedirectSeconds((current) => {
        if (current <= 1) {
          window.clearInterval(interval);
          navigate("home");
          return 0;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(interval);
  }, [verificationSuccess]);

  function navigate(nextView: ViewKey) {
    setView(nextView);
    const path = VIEW_PATHS[nextView] || "/workspace";
    if (window.location.pathname !== path) {
      window.history.pushState(null, "", path);
    }
  }

  function acceptAuthPayload(payload: { token: string; principal: Principal }) {
    setToken(payload.token);
    setPrincipal(payload.principal);
    setAuthenticated(true);
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
    setAuthSessions([]);
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
    acceptAuthPayload(payload);
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
    const verificationCode = payload.verification_code ? ` Dev code: ${String(payload.verification_code)}` : "";
    notify(`Registration created. Check your email for the confirmation link or code.${verificationUrl}${verificationCode}`, "success");
  }

  async function verifyEmail() {
    const payload = await api.post<{ token: string; principal: Principal }>("/auth/verify", {
      email: credentials.email,
      code: credentials.verificationCode,
      token: credentials.verificationCode,
    });
    acceptAuthPayload(payload);
    setVerificationSuccess(true);
    setRedirectSeconds(5);
    window.history.replaceState(null, "", "/login?verified=1");
    notify("Email confirmed. You are signed in.", "success");
  }

  async function forgotPassword() {
    const payload = await api.post<Dict>("/auth/forgot-password", { email: credentials.email });
    const resetCode = payload.reset_code ? ` Dev code: ${String(payload.reset_code)}` : "";
    const resetToken = payload.reset_token ? ` Dev token: ${String(payload.reset_token)}` : "";
    notify(`If that email exists, Planora sent a password reset link and code.${resetCode}${resetToken}`, "success");
  }

  async function resetPassword() {
    const payload = await api.post<{ token: string; principal: Principal }>("/auth/reset-password", {
      email: credentials.email,
      code: credentials.resetCode,
      token: credentials.resetToken || credentials.resetCode,
      new_password: credentials.newPassword,
    });
    acceptAuthPayload(payload);
    setVerificationSuccess(true);
    setRedirectSeconds(5);
    window.history.replaceState(null, "", "/login?verified=1");
    notify("Password reset. You are signed in.", "success");
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

  async function changePassword(currentPassword: string, newPassword: string) {
    await api.post<Dict>("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    });
    notify("Password changed. Other sessions were revoked.", "success");
    const payload = await api.get<{ sessions: Dict[] }>("/auth/sessions");
    setAuthSessions(payload.sessions || []);
  }

  async function revokeOtherSessions() {
    const payload = await api.post<{ sessions: Dict[] }>("/auth/sessions", {});
    setAuthSessions(payload.sessions || []);
    notify("Other sessions revoked.", "success");
  }

  async function resendVerification() {
    const payload = await api.post<Dict>("/auth/resend-verification", {});
    const code = payload.verification_code ? ` Dev code: ${String(payload.verification_code)}` : "";
    notify(`Verification email sent.${code}`, "success");
  }

  async function refreshAdmin(filters: Dict = {}) {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (String(value ?? "").trim()) query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const [audit, analyticsPayload] = await Promise.all([
      api.get<{ events: Dict[] }>(`/audit${suffix}`),
      api.get<Dict>(`/analytics/summary${suffix}`),
    ]);
    setAuditEvents(audit.events || []);
    setAnalyticsSummary(analyticsPayload);
    notify("Admin data refreshed", "success");
  }

  async function sendEmailTest(email: string) {
    await api.post<Dict>("/system/email-test", { email });
    notify("Test email sent. Check the destination inbox and spam folder.", "success");
  }

  async function importCsv(filename: string, content: string, fieldMap: Dict<string>) {
    setBusy(true);
    try {
      const payload = await api.post<Dict>("/import/csv", {
        filename,
        content,
        field_map: fieldMap,
        lock_imported: false,
      });
      setInstance(payload.instance as Instance);
      setSchedule((payload.schedule || {}) as Schedule);
      setScore((payload.score || {}) as Dict);
      const importMeta = (payload.meta || {}) as Dict;
      const validationErrors = Array.isArray(importMeta.validation_errors) ? importMeta.validation_errors as string[] : [];
      setConflicts(validationErrors);
      setSessionId("");
      setSelectedActivityId("");
      setHeldActivityId("");
      setMoveTargets([]);
      setSelectedWeek(Number((payload.instance as Instance)?.weeks?.[0] || 1));
      trackAnalytics("csv_imported", { filename, validation_errors: validationErrors.length });
      notify(`Imported ${filename}`, validationErrors.length ? "info" : "success");
      navigate("workspace");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
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
    setJobStatus(payload);
    trackAnalytics("improve_job_started", { job_id: payload.job_id, iterations: settings.improveIterations });
    notify(`Background improve job ${String(payload.job_id || "")} started`, "success");
  }

  useEffect(() => {
    const jobId = String(jobStatus?.job_id || "");
    const status = String(jobStatus?.status || "");
    if (!jobId || ["done", "failed", "cancelled"].includes(status)) return undefined;
    const interval = window.setInterval(() => {
      api.get<Dict>(`/jobs/${encodeURIComponent(jobId)}`).then((payload) => {
        setJobStatus(payload);
        if (payload.status === "done") {
          const result = (payload.result || {}) as Dict;
          if (result.schedule) setSchedule(result.schedule as Schedule);
          if (result.global_after || result.after) setScore((result.global_after || result.after) as Dict);
          notify("Background improve job finished", "success");
        }
        if (payload.status === "failed") {
          notify(String(payload.error || "Background job failed"), "error");
        }
      }).catch((error: unknown) => notify(String(error), "error"));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [api, jobStatus?.job_id, jobStatus?.status]);

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
        onForgotPassword={() => forgotPassword().catch((error: unknown) => notify(String(error), "error"))}
        onResetPassword={() => resetPassword().catch((error: unknown) => notify(String(error), "error"))}
        onCredentialsChange={setCredentials}
        verificationSuccess={verificationSuccess}
        redirectSeconds={redirectSeconds}
        initialMode={loginInitialMode}
        onRedirectNow={() => navigate("home")}
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

  const privacyContent = (
    <div className="faq-page">
      <section className="panel faq-hero">
        <h1>Privacy</h1>
        <p>Planora keeps operational scheduling data tenant-scoped and uses only essential cookies unless analytics is explicitly enabled.</p>
      </section>
      <section className="faq-grid">
        {[
          ["Essential cookies", "Login sessions, CSRF protection, and cookie consent are required for the app to work securely."],
          ["Analytics cookies", "Optional first-party analytics records page views and product events with a pseudonymous client ID. You can opt out from the footer at any time."],
          ["University separation", "Each organization has its own tenant scope. Students, TAs, professors, and university admins only see data permitted by their role and active organization."],
          ["Admin visibility", "Global admins can review audit events, analytics totals, and operational health across tenants for support and abuse prevention."],
          ["Data exports", "Admins can export audit and analytics CSVs from the Admin page. Schedule CSV imports and exports stay inside the authenticated organization workflow."],
          ["Email", "Planora sends verification, password reset, and deliverability-test emails through the configured SMTP provider."],
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
        canEdit={principal.permissions.includes("schedule:write") || principal.permissions.includes("solver:run")}
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
    privacy: privacyContent,
    login: loginContent,
    account: (
      <AccountPanel
        principal={principal}
        organizations={organizations}
        sessions={authSessions}
        onJoinInvite={joinInvite}
        onSwitchOrganization={switchOrganization}
        onChangePassword={changePassword}
        onRevokeOtherSessions={revokeOtherSessions}
        onResendVerification={resendVerification}
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
            onImportCsv={importCsv}
            jobStatus={jobStatus}
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
    admin: (
      <AdminPanel
        principal={principal}
        auditEvents={auditEvents}
        system={system}
        analytics={analyticsSummary}
        onRefresh={refreshAdmin}
        onEmailTest={sendEmailTest}
        apiBaseUrl={api.baseUrl.replace(/\/$/, "")}
      />
    ),
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
