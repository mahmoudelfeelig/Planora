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
import { FaqContent, HomeContent, PrivacyContent } from "./components/PublicPages";
import { ReviewPanel } from "./components/ReviewPanel";
import { ScheduleBoard } from "./components/ScheduleBoard";
import { SettingsPanel } from "./components/SettingsPanel";
import { InsightsPanel } from "./components/InsightsPanel";
import {
  analyticsClientId,
  clearCookie,
  readStoredAuthToken,
  readAnalyticsConsent,
  readStoredTheme,
  setCookie,
  writeStoredAuthToken,
  type AnalyticsConsent,
  type ThemeMode,
} from "./browser_state";
import { VIEW_PATHS, viewFromLocation } from "./navigation";
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

type Toast = {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
};

type LoginInitialMode = "login" | "register" | "verify" | "forgot" | "reset";

const homeContent = <HomeContent />;
const faqContent = <FaqContent />;
const privacyContent = <PrivacyContent />;

export function App() {
  const [principal, setPrincipal] = useState<Principal>(DEFAULT_PRINCIPAL);
  const [token, setToken] = useState(readStoredAuthToken);
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
  const [systemStatus, setSystemStatus] = useState<Dict>({});
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
  const tokenRef = useRef(token);

  const api = useMemo(
    () => createApiClient(API_DEFAULT, principal, token),
    [principal, token],
  );

  useEffect(() => {
    tokenRef.current = token;
  }, [token]);

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
    if (!authenticated && navigator.sendBeacon) {
      const sent = navigator.sendBeacon(target, new Blob([body], { type: "application/json" }));
      if (sent) return;
    }
    fetch(target, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
      keepalive: true,
      credentials: "include",
    }).catch(() => undefined);
  }, [analyticsConsent, authenticated, principal.role, principal.tenant_id, token, view]);

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

  function clearAuthState() {
    writeStoredAuthToken("");
    setToken("");
    setAuthenticated(false);
    setPrincipal(DEFAULT_PRINCIPAL);
    setAccessSnapshot({});
    setOrganizations([]);
    setAuthSessions([]);
    setPresets([]);
    setProjects([]);
    setParity({});
    setAuditEvents([]);
    setSystem({});
    setSystemStatus({});
    setAnalyticsSummary({});
  }

  const refreshBootstrap = useCallback(async (client = api) => {
    const authPayload = await client.get<Dict>("/auth/config");
    setAuthConfig(authPayload);
    const whoami = await client.get<Principal>("/auth/whoami");
    const [presetPayload, projectPayload, parityPayload] = await Promise.all([
      client.get<{ presets: string[] }>("/presets"),
      client.get<{ projects: Dict[] }>("/projects"),
      client.get<Dict>("/parity"),
    ]);
    const [organizationPayload, sessionPayload] = await Promise.all([
      client.get<{ organizations: OrganizationMembership[] }>("/access/my-organizations"),
      client.get<{ sessions: Dict[] }>("/auth/sessions"),
    ]);
    setPrincipal(whoami);
    setAuthenticated(true);
    setPresets(presetPayload.presets || []);
    setProjects(projectPayload.projects || []);
    setParity(parityPayload);
    setOrganizations(organizationPayload.organizations || []);
    setAuthSessions(sessionPayload.sessions || []);
    if (whoami.permissions.includes("audit:read")) {
      const [audit, analyticsPayload] = await Promise.all([
        client.get<{ events: Dict[] }>("/audit"),
        client.get<Dict>("/analytics/summary"),
      ]);
      setAuditEvents(audit.events || []);
      setAnalyticsSummary(analyticsPayload);
    } else {
      setAuditEvents([]);
      setAnalyticsSummary({});
    }
    if (whoami.is_global_admin) {
      const [systemPayload, statusPayload] = await Promise.all([
        client.get<Dict>("/system"),
        client.get<Dict>("/system/status"),
      ]);
      setSystem(systemPayload);
      setSystemStatus(statusPayload);
    } else {
      setSystem({});
      setSystemStatus({});
    }
    if (whoami.permissions.includes("access:manage")) {
      setAccessSnapshot(await client.get<Dict>("/access"));
    } else {
      setAccessSnapshot({});
    }
  }, [api]);

  useEffect(() => {
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    const publicPath = ["/", "/login", "/faq", "/privacy"].includes(window.location.pathname);
    const cookieApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
    if (api.token || publicPath) {
      if (api.token) {
        writeStoredAuthToken("");
        setToken("");
      }
      cookieApi.post<{ token: string; principal: Principal }>("/auth/refresh", {})
        .then(async (payload) => {
          const authenticatedApi = acceptAuthPayload(payload);
          await refreshBootstrap(authenticatedApi);
        })
        .catch(async () => {
          if (publicPath) {
            cookieApi.get<Dict>("/auth/config")
              .then(setAuthConfig)
              .catch((error: unknown) => notify(String(error), "error"));
            return;
          }
          try {
            await refreshBootstrap(cookieApi);
          } catch (error) {
            clearAuthState();
            if (!publicPath) {
              notify("Sign in or create an account to continue.", "info");
              window.history.replaceState(null, "", "/login");
              setView("login");
            } else if (error instanceof ApiError && error.status === 429) {
              const wait = error.retryAfter ? ` Try again in ${error.retryAfter} seconds.` : " Try again shortly.";
              notify(`The server is temporarily busy.${wait}`, "error");
            } else if (!(error instanceof ApiError && [401, 403].includes(error.status))) {
              notify(String(error), "error");
            }
          }
        });
      return;
    }
    refreshBootstrap().catch(async (error: unknown) => {
      const authenticationFailure = error instanceof ApiError && [401, 403].includes(error.status);
      if (authenticationFailure) {
        if (api.token !== tokenRef.current) return;
        if (api.token) {
          try {
            writeStoredAuthToken("");
            setToken("");
            const cookieApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
            const payload = await cookieApi.post<{ token: string; principal: Principal }>("/auth/refresh", {});
            const authenticatedApi = acceptAuthPayload(payload);
            await refreshBootstrap(authenticatedApi);
            return;
          } catch {
            // Fall through to the normal signed-out state if the cookie is not valid either.
          }
        }
        clearAuthState();
        if (!publicPath) {
          notify("Sign in or create an account to continue.", "info");
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
  }, [api, refreshBootstrap]);

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

  useEffect(() => {
    if (!authenticated || view !== "login" || verificationSuccess) return;
    const path = VIEW_PATHS.workspace;
    if (window.location.pathname !== path) {
      window.history.replaceState(null, "", path);
    }
    setView("workspace");
  }, [authenticated, verificationSuccess, view]);

  function acceptAuthPayload(payload: { token: string; principal: Principal }) {
    writeStoredAuthToken(payload.token);
    setToken(payload.token);
    setPrincipal(payload.principal);
    setAuthenticated(true);
    return createApiClient(API_DEFAULT, payload.principal, payload.token);
  }

  async function signOut() {
    trackAnalytics("logout");
    try {
      await api.post<Dict>("/auth/logout", {});
    } catch (error) {
      notify(`Could not securely sign out: ${String(error)}`, "error");
      return;
    }
    clearAuthState();
    setInstance(null);
    setSchedule({});
    setSessionId("");
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
      notify(`Loaded ${mode}. Run Solve to create the schedule.`, "success");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function login() {
    const authApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
    const payload = await authApi.post<{ token: string; principal: Principal }>("/auth/login", {
      email: credentials.email,
      password: credentials.password,
    });
    const authenticatedApi = acceptAuthPayload(payload);
    await refreshBootstrap(authenticatedApi);
    trackAnalytics("login_success", { role: payload.principal.role, tenant_id: payload.principal.tenant_id });
    notify("Signed in", "success");
    navigate("workspace");
  }

  async function register() {
    const authApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
    const payload = await authApi.post<Dict>("/auth/register", {
      email: credentials.email,
      password: credentials.password,
      display_name: credentials.displayName,
    });
    if (payload.token && payload.principal) {
      const authPayload = payload as { token: string; principal: Principal };
      const authenticatedApi = acceptAuthPayload(authPayload);
      await refreshBootstrap(authenticatedApi);
      trackAnalytics("registration_complete", { role: authPayload.principal.role, tenant_id: authPayload.principal.tenant_id });
      notify("Account created. You are signed in.", "success");
      navigate("workspace");
      return false;
    }
    const verificationUrl = payload.verification_url ? ` Dev verification link: ${String(payload.verification_url)}` : "";
    const verificationCode = payload.verification_code ? ` Dev code: ${String(payload.verification_code)}` : "";
    notify(`Registration created. Check your email for the confirmation link or code.${verificationUrl}${verificationCode}`, "success");
    return true;
  }

  async function verifyEmail() {
    const authApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
    const payload = await authApi.post<{ token: string; principal: Principal }>("/auth/verify", {
      email: credentials.email,
      code: credentials.verificationCode,
      token: credentials.verificationCode,
    });
    const authenticatedApi = acceptAuthPayload(payload);
    await refreshBootstrap(authenticatedApi);
    setVerificationSuccess(true);
    setRedirectSeconds(5);
    window.history.replaceState(null, "", "/login?verified=1");
    notify("Email confirmed. You are signed in.", "success");
  }

  async function forgotPassword() {
    const authApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
    const payload = await authApi.post<Dict>("/auth/forgot-password", { email: credentials.email });
    const resetCode = payload.reset_code ? ` Dev code: ${String(payload.reset_code)}` : "";
    const resetToken = payload.reset_token ? ` Dev token: ${String(payload.reset_token)}` : "";
    notify(`If that email exists, Planora sent a password reset link and code.${resetCode}${resetToken}`, "success");
  }

  async function resetPassword() {
    const authApi = createApiClient(API_DEFAULT, DEFAULT_PRINCIPAL, "");
    const payload = await authApi.post<{ token: string; principal: Principal }>("/auth/reset-password", {
      email: credentials.email,
      code: credentials.resetCode,
      token: credentials.resetToken || credentials.resetCode,
      new_password: credentials.newPassword,
    });
    const authenticatedApi = acceptAuthPayload(payload);
    await refreshBootstrap(authenticatedApi);
    setVerificationSuccess(true);
    setRedirectSeconds(5);
    window.history.replaceState(null, "", "/login?verified=1");
    notify("Password reset. You are signed in.", "success");
  }

  async function applyAccessChange(change: Dict) {
    const next = await api.post<Dict>("/access", change);
    await refreshBootstrap();
    setAccessSnapshot(next);
    notify("Access settings updated", "success");
  }

  async function joinInvite(code: string) {
    const payload = await api.post<{ token: string; principal: Principal; organizations: OrganizationMembership[] }>("/access/join-invite", { invite_code: code });
    const authenticatedApi = acceptAuthPayload(payload);
    await refreshBootstrap(authenticatedApi);
    trackAnalytics("invite_joined", { tenant_id: payload.principal.tenant_id, role: payload.principal.role });
    notify("Group joined. Your active organization and permissions have been refreshed.", "success");
  }

  async function switchOrganization(tenantId: string) {
    const payload = await api.post<{ token: string; principal: Principal; organizations: OrganizationMembership[] }>("/access/switch-organization", { tenant_id: tenantId });
    const authenticatedApi = acceptAuthPayload(payload);
    await refreshBootstrap(authenticatedApi);
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

  async function refreshAdmin(filters: Dict = {}) {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (String(value ?? "").trim()) query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const [audit, statusPayload, analyticsPayload] = await Promise.all([
      api.get<{ events: Dict[] }>(`/audit${suffix}`),
      api.get<Dict>("/system/status"),
      api.get<Dict>(`/analytics/summary${suffix}`),
    ]);
    setAuditEvents(audit.events || []);
    setSystemStatus(statusPayload);
    setAnalyticsSummary(analyticsPayload);
    notify("Admin data refreshed", "success");
  }

  async function saveCurrentProject(name: string) {
    if (!instance) throw new Error("Load a scenario before saving a project.");
    await api.post<Dict>("/projects", { name, instance, schedule, meta: { source: "react-web" } });
    await refreshBootstrap();
    notify(`Saved project ${name}`, "success");
  }

  async function openProject(project: Dict) {
    const tenant = String(project.tenant_id || principal.tenant_id);
    const payload = await api.get<Dict>(`/projects/${encodeURIComponent(String(project.name))}?tenant_id=${encodeURIComponent(tenant)}`);
    setInstance(payload.instance as Instance);
    setSchedule((payload.schedule || {}) as Schedule);
    setScore((((payload.meta || {}) as Dict).quality || {}) as Dict);
    setSessionId("");
    setSelectedActivityId("");
    setHeldActivityId("");
    setMoveTargets([]);
    setSelectedWeek(Number((payload.instance as Instance)?.weeks?.[0] || 1));
    notify(`Opened project ${String(project.name)}`, "success");
    navigate("workspace");
  }

  async function deleteProject(project: Dict) {
    const tenant = String(project.tenant_id || principal.tenant_id);
    await api.delete(`/projects/${encodeURIComponent(String(project.name))}?tenant_id=${encodeURIComponent(tenant)}`);
    await refreshBootstrap();
    notify(`Deleted project ${String(project.name)}`, "success");
  }

  async function renameProject(project: Dict, nextName: string) {
    const tenant = String(project.tenant_id || principal.tenant_id);
    const payload = await api.get<Dict>(`/projects/${encodeURIComponent(String(project.name))}?tenant_id=${encodeURIComponent(tenant)}`);
    await api.post<Dict>("/projects", {
      name: nextName,
      tenant_id: tenant,
      instance: payload.instance,
      schedule: payload.schedule,
      meta: payload.meta,
    });
    await api.delete(`/projects/${encodeURIComponent(String(project.name))}?tenant_id=${encodeURIComponent(tenant)}`);
    await refreshBootstrap();
    notify(`Renamed project to ${nextName}`, "success");
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
      const scoredConflicts = Array.isArray((payload.score as Dict | undefined)?.hard_conflicts)
        ? ((payload.score as Dict).hard_conflicts as string[])
        : [];
      const importedConflicts = Array.from(new Set([...validationErrors, ...scoredConflicts].map(String)));
      setConflicts(importedConflicts);
      setSessionId("");
      setSelectedActivityId("");
      setHeldActivityId("");
      setMoveTargets([]);
      setSelectedWeek(Number((payload.instance as Instance)?.weeks?.[0] || 1));
      trackAnalytics("csv_imported", { filename, validation_errors: validationErrors.length, hard_conflicts: importedConflicts.length });
      notify(`Imported ${filename}${importedConflicts.length ? ` with ${importedConflicts.length} issue(s)` : ""}`, importedConflicts.length ? "info" : "success");
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
        hard_constraints: {
          force_repeat_weekly_pattern: settings.forceRepeatWeeklyPattern,
        },
        options: {
          room_mode: settings.roomMode,
          use_objective: settings.useObjective,
          retry_without_objective: true,
          objective_profile: settings.profile,
          time_limit_seconds: settings.timeLimitSeconds,
          workers: settings.workers,
        },
      });
      const result = payload.result as Dict;
      const hardConflicts = Array.isArray(result.hard_conflicts) ? result.hard_conflicts : [];
      setConflicts(hardConflicts as string[]);
      const rawStatus = Number(result.raw_status);
      const feasible = [2, 4].includes(rawStatus) && Boolean(result.schedule) && Object.keys((result.schedule || {}) as Dict).length > 0;
      if (feasible) {
        setSchedule(result.schedule as Schedule);
        setScore(((result.meta as Dict)?.quality || {}) as Dict);
        navigate("workspace");
      }
      trackAnalytics("solve_complete", { status: result.status, hard_conflicts: hardConflicts.length });
      notify(feasible ? "Solve complete" : `No feasible schedule was produced (status ${String(result.status ?? rawStatus)}). The current timetable was preserved.`, feasible ? "success" : "error");
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
      const nextSchedule = result.schedule as Schedule | undefined;
      if (!nextSchedule || !Object.keys(nextSchedule).length) {
        throw new Error("Improve finished without a valid schedule; the current timetable was preserved.");
      }
      setSchedule(nextSchedule);
      setScore((result.global_after || result.after || score) as Dict);
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
    if (!jobId || ["complete", "done", "failed", "cancelled"].includes(status)) return undefined;
    let cancelled = false;
    let timeout = 0;
    const poll = async () => {
      try {
        const payload = await api.get<Dict>(`/jobs/${encodeURIComponent(jobId)}`);
        if (cancelled) return;
        setJobStatus(payload);
        if (["complete", "done"].includes(String(payload.status))) {
          const result = (payload.result || {}) as Dict;
          if (result.schedule) setSchedule(result.schedule as Schedule);
          if (result.global_after || result.after) setScore((result.global_after || result.after) as Dict);
          notify("Background improve job finished", "success");
        }
        if (payload.status === "failed") {
          notify(String(payload.error || "Background job failed"), "error");
        }
        if (!["complete", "done", "failed", "cancelled"].includes(String(payload.status))) {
          timeout = window.setTimeout(poll, 1000);
        }
      } catch (error) {
        if (!cancelled) {
          notify(String(error), "error");
          timeout = window.setTimeout(poll, 2000);
        }
      }
    };
    timeout = window.setTimeout(poll, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [api, jobStatus?.job_id, jobStatus?.status]);

  async function holdSelected(activityId?: string) {
    const id = activityId || selectedActivityId;
    if (!id) return;
    const sid = await ensureSession(instance, schedule);
    const payload = await api.post<Dict>(`/sessions/${sid}/move-deltas`, {
      activity_id: Number(id),
      week: selectedWeek,
      limit: 60,
    });
    const result = payload.result as Dict;
    setSelectedActivityId(id);
    setHeldActivityId(id);
    setMoveTargets((result.targets || []) as Dict[]);
    notify(`Previewing move targets for A${id}`, "info");
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

  const loginContent = (
    <div className="auth-page">
      <LoginPanel
        key={loginInitialMode}
        authConfig={authConfig}
        credentials={credentials}
        onLogin={() => login().catch((error: unknown) => notify(String(error), "error"))}
        onRegister={() => register().catch((error: unknown) => {
          notify(String(error), "error");
          return false;
        })}
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
        onHold={(id) => holdSelected(id).catch((error: unknown) => notify(String(error), "error"))}
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
            scheduleActivities={Object.keys(schedule).length}
          />
          <RunSummary score={score} conflicts={conflicts} />
        </div>
      </div>
    ),
    settings: <SettingsPanel settings={settings} onChange={setSettings} />,
    fairness: <InsightsPanel instance={instance} schedule={schedule} />,
    projects: (
      <ProjectsPanel
        projects={projects}
        canWrite={principal.permissions.includes("projects:write")}
        canSave={Boolean(instance)}
        onRefresh={() => refreshBootstrap().catch((error: unknown) => notify(String(error), "error"))}
        onSave={(name) => saveCurrentProject(name).catch((error: unknown) => notify(String(error), "error"))}
        onOpen={(project) => openProject(project).catch((error: unknown) => notify(String(error), "error"))}
        onDelete={(project) => deleteProject(project).catch((error: unknown) => notify(String(error), "error"))}
        onRename={(project, name) => renameProject(project, name).catch((error: unknown) => notify(String(error), "error"))}
      />
    ),
    parity: <ParityPanel manifest={parity} />,
    access: <AccessPanel principal={principal} snapshot={accessSnapshot} onChange={applyAccessChange} />,
    admin: (
      <AdminPanel
        principal={principal}
        auditEvents={auditEvents}
        system={system}
        systemStatus={systemStatus}
        analytics={analyticsSummary}
        onRefresh={refreshAdmin}
        onEmailTest={sendEmailTest}
        onDownload={(path, filename) => api.download(path, filename).catch((error: unknown) => notify(String(error), "error"))}
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
