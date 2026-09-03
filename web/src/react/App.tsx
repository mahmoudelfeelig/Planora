import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ArrowRight, CheckCircle, Info, Warning, X } from "@phosphor-icons/react";
import { ApiError, createApiClient, createUnauthenticatedApiClient, DEFAULT_PRINCIPAL } from "./api";
import { AccountPanel } from "./components/AccountPanel";
import { AdminPanel } from "./components/AdminPanel";
import { AccessPanel } from "./components/AccessPanel";
import { AppShell } from "./components/AppShell";
import { LoginPanel } from "./components/LoginPanel";
import { OperationsPanel } from "./components/OperationsPanel";
import { ParityPanel } from "./components/ParityPanel";
import { ProjectsPanel } from "./components/ProjectsPanel";
import { FaqContent, HomeContent, PrivacyContent } from "./components/PublicPages";
import { ReviewPanel } from "./components/ReviewPanel";
import { ScheduleBoard } from "./components/ScheduleBoard";
import { SettingsPanel } from "./components/SettingsPanel";
import { InsightsPanel } from "./components/InsightsPanel";
import { Tutorial } from "./components/Tutorial";
import {
  analyticsClientId,
  clearCookie,
  readAnalyticsConsent,
  readStoredTheme,
  setCookie,
  type AnalyticsConsent,
  type ThemeMode,
} from "./browser_state";
import { VIEW_PATHS, viewFromLocation } from "./navigation";
import type { Dict, Instance, OrganizationMembership, Principal, Schedule, ViewKey } from "./types";
import { DEFAULT_SETTINGS, type SolverSettings } from "./solver_settings";
import {
  DEFAULT_UI_CONTRACT,
  loadUiContract,
  PlannerApi,
  type UiContract,
  type UiScenario,
} from "./planner_api";

const API_DEFAULT = import.meta.env.VITE_PLANORA_API_URL || "http://127.0.0.1:8787";

type Toast = {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
  action?: {
    label: string;
    onClick(): void;
  };
};

type LoginInitialMode = "login" | "register" | "verify" | "forgot" | "reset";

const homeContent = <HomeContent />;
const faqContent = <FaqContent />;
const privacyContent = <PrivacyContent />;

export function App() {
  const [principal, setPrincipal] = useState<Principal>(DEFAULT_PRINCIPAL);
  const [authenticated, setAuthenticated] = useState(false);
  const [view, setView] = useState<ViewKey>(viewFromLocation);
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
  const [selectedActivityId, setSelectedActivityId] = useState("");
  const [heldActivityId, setHeldActivityId] = useState("");
  const [moveTargets, setMoveTargets] = useState<Dict[]>([]);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [advancedOverridesEnabled, setAdvancedOverridesEnabled] = useState(false);
  const [uiContract, setUiContract] = useState<UiContract>(DEFAULT_UI_CONTRACT);
  const [runMode, setRunMode] = useState("balanced");
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [theme, setTheme] = useState<ThemeMode>(readStoredTheme);
  const [analyticsConsent, setAnalyticsConsent] = useState<AnalyticsConsent>(readAnalyticsConsent);
  const [verificationSuccess, setVerificationSuccess] = useState(false);
  const [redirectSeconds, setRedirectSeconds] = useState(5);
  const [loginInitialMode, setLoginInitialMode] = useState<LoginInitialMode>("login");
  const bootstrapStarted = useRef(false);

  const api = useMemo(
    () => createApiClient(API_DEFAULT, principal, ""),
    [principal],
  );
  const planner = useMemo(() => new PlannerApi(api), [api]);

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
      },
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

  function notify(message: string, kind: Toast["kind"] = "info", action?: Toast["action"]) {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current.slice(-3), { id, kind, message, action }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5200);
  }

  function dismissToast(id: number) {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }

  function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  function clearAuthState() {
    setAuthenticated(false);
    setPrincipal(DEFAULT_PRINCIPAL);
    setAccessSnapshot({});
    setOrganizations([]);
    setAuthSessions([]);
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
    const [projectPayload, parityPayload, uiContractPayload] = await Promise.all([
      client.get<{ projects: Dict[] }>("/projects"),
      client.get<Dict>("/parity"),
      loadUiContract(client),
    ]);
    const [organizationPayload, sessionPayload] = await Promise.all([
      client.get<{ organizations: OrganizationMembership[] }>("/access/my-organizations"),
      client.get<{ sessions: Dict[] }>("/auth/sessions"),
    ]);
    setPrincipal(whoami);
    setAuthenticated(true);
    setProjects(projectPayload.projects || []);
    setParity(parityPayload);
    setUiContract(uiContractPayload);
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
    if (!authenticated) return;
    if (localStorage.getItem("planora_tutorial_seen_v1") !== "1") setTutorialOpen(true);
  }, [authenticated]);

  useEffect(() => {
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    const publicPath = ["/", "/login", "/faq", "/privacy"].includes(window.location.pathname);
    const cookieApi = createUnauthenticatedApiClient(API_DEFAULT);
    refreshBootstrap(cookieApi).catch((error: unknown) => {
      const authenticationFailure = error instanceof ApiError && [401, 403].includes(error.status);
      if (authenticationFailure) {
        clearAuthState();
        if (publicPath) {
          cookieApi.get<Dict>("/auth/config")
            .then(setAuthConfig)
            .catch((configError: unknown) => notify(String(configError), "error"));
        } else {
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

  useEffect(() => {
    if (!authenticated || view !== "login" || verificationSuccess) return;
    const path = VIEW_PATHS.workspace;
    if (window.location.pathname !== path) {
      window.history.replaceState(null, "", path);
    }
    setView("workspace");
  }, [authenticated, verificationSuccess, view]);

  function acceptAuthPayload(payload: { token: string; principal: Principal }) {
    setPrincipal(payload.principal);
    setAuthenticated(true);
    return createApiClient(API_DEFAULT, payload.principal, "");
  }

  async function refreshAfterAuth(client: ReturnType<typeof createApiClient>) {
    try {
      await refreshBootstrap(client);
    } catch (error) {
      notify(`Signed in, but workspace data did not finish loading: ${errorMessage(error)}`, "error");
    }
  }

  async function signOut() {
    trackAnalytics("logout");
    let logoutError: unknown = null;
    try {
      await api.post<Dict>("/auth/logout", {});
    } catch (error) {
      logoutError = error;
    }
    clearAuthState();
    setInstance(null);
    setSchedule({});
    setSessionId("");
    notify(
      logoutError ? `Signed out locally. The server logout call failed: ${errorMessage(logoutError)}` : "Signed out",
      logoutError ? "error" : "info",
    );
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

  async function loadScenario(scenario: UiScenario) {
    if (scenario.id === "import") {
      navigate("operations");
      return;
    }
    setBusy(true);
    try {
      const payload = await planner.loadScenario(scenario);
      setInstance(payload.instance);
      setSchedule({});
      setScore({});
      setConflicts([]);
      setSessionId("");
      setSelectedActivityId("");
      setHeldActivityId("");
      setMoveTargets([]);
      setSelectedWeek(Number(payload.instance.weeks?.[0] || 1));
      trackAnalytics("scenario_loaded", { scenario: scenario.id });
      notify(`Loaded ${scenario.label}. Build a schedule when you are ready.`, "success", {
        label: "Open schedule",
        onClick: () => navigate("workspace"),
      });
      navigate("workspace");
    } catch (error) {
      notify(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function login() {
    const authApi = createUnauthenticatedApiClient(API_DEFAULT);
    const payload = await authApi.post<{ token: string; principal: Principal }>("/auth/login", {
      email: credentials.email,
      password: credentials.password,
    });
    const authenticatedApi = acceptAuthPayload(payload);
    trackAnalytics("login_success", { role: payload.principal.role, tenant_id: payload.principal.tenant_id });
    notify("Signed in", "success");
    navigate("workspace");
    await refreshAfterAuth(authenticatedApi);
  }

  async function register() {
    const authApi = createUnauthenticatedApiClient(API_DEFAULT);
    const payload = await authApi.post<Dict>("/auth/register", {
      email: credentials.email,
      password: credentials.password,
      display_name: credentials.displayName,
    });
    if (payload.token && payload.principal) {
      const authPayload = payload as { token: string; principal: Principal };
      const authenticatedApi = acceptAuthPayload(authPayload);
      trackAnalytics("registration_complete", { role: authPayload.principal.role, tenant_id: authPayload.principal.tenant_id });
      notify("Account created. You are signed in.", "success");
      navigate("workspace");
      await refreshAfterAuth(authenticatedApi);
      return false;
    }
    const verificationUrl = payload.verification_url ? ` Dev verification link: ${String(payload.verification_url)}` : "";
    const verificationCode = payload.verification_code ? ` Dev code: ${String(payload.verification_code)}` : "";
    notify(`Registration created. Check your email for the confirmation link or code.${verificationUrl}${verificationCode}`, "success");
    return true;
  }

  async function verifyEmail() {
    const authApi = createUnauthenticatedApiClient(API_DEFAULT);
    const payload = await authApi.post<{ token: string; principal: Principal }>("/auth/verify", {
      email: credentials.email,
      code: credentials.verificationCode,
      token: credentials.verificationCode,
    });
    const authenticatedApi = acceptAuthPayload(payload);
    setVerificationSuccess(true);
    setRedirectSeconds(5);
    window.history.replaceState(null, "", "/login?verified=1");
    notify("Email confirmed. You are signed in.", "success");
    await refreshAfterAuth(authenticatedApi);
  }

  async function forgotPassword() {
    const authApi = createUnauthenticatedApiClient(API_DEFAULT);
    const payload = await authApi.post<Dict>("/auth/forgot-password", { email: credentials.email });
    const resetCode = payload.reset_code ? ` Dev code: ${String(payload.reset_code)}` : "";
    const resetToken = payload.reset_token ? ` Dev token: ${String(payload.reset_token)}` : "";
    notify(`If that email exists, Planora sent a password reset link and code.${resetCode}${resetToken}`, "success");
  }

  async function resetPassword() {
    const authApi = createUnauthenticatedApiClient(API_DEFAULT);
    const payload = await authApi.post<{ token: string; principal: Principal }>("/auth/reset-password", {
      email: credentials.email,
      code: credentials.resetCode,
      token: credentials.resetToken || credentials.resetCode,
      new_password: credentials.newPassword,
    });
    const authenticatedApi = acceptAuthPayload(payload);
    setVerificationSuccess(true);
    setRedirectSeconds(5);
    window.history.replaceState(null, "", "/login?verified=1");
    notify("Password reset. You are signed in.", "success");
    await refreshAfterAuth(authenticatedApi);
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
      const payload = await planner.solve(
        sid,
        runMode,
        settings,
        advancedOverridesEnabled,
      );
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
      const payload = await planner.validate(sid);
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
      const payload = await planner.improve(
        sid,
        runMode,
        settings,
        advancedOverridesEnabled,
      );
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
    <div className="workspace-page">
      <ScheduleBoard
        instance={instance}
        schedule={schedule}
        selectedWeek={selectedWeek}
        targets={moveTargets}
        heldActivityId={heldActivityId}
        selectedActivityId={selectedActivityId}
        conflicts={conflicts}
        score={score}
        runModeLabel={uiContract.modes.find((mode) => mode.id === runMode)?.label || "Balanced"}
        busy={busy}
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
        onOpenData={() => navigate("operations")}
        onSolve={solve}
        onImprove={improve}
        onValidate={scoreCurrent}
        onPublish={() => {
          if (conflicts.length) {
            notify("Resolve hard conflicts before publishing.", "error");
            navigate("review");
            return;
          }
          notify("Draft is ready to save or publish from Projects.", "success", {
            label: "Open projects",
            onClick: () => navigate("projects"),
          });
          navigate("projects");
        }}
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
      <OperationsPanel
        instance={instance}
        scenarios={uiContract.scenarios}
        modes={uiContract.modes}
        runMode={runMode}
        busy={busy}
        onRunModeChange={(mode) => {
          setRunMode(mode);
          setAdvancedOverridesEnabled(false);
        }}
        onLoadScenario={(scenario) => void loadScenario(scenario)}
        onImportCsv={importCsv}
      />
    ),
    settings: (
      <SettingsPanel
        settings={settings}
        overridesEnabled={advancedOverridesEnabled}
        onChange={(next) => {
          setSettings(next);
          setAdvancedOverridesEnabled(true);
        }}
        onUseModeDefaults={() => setAdvancedOverridesEnabled(false)}
      />
    ),
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
      onTutorialOpen={() => setTutorialOpen(true)}
      onAnalyticsConsentChange={setAnalyticsConsent}
    >
      {content[view]}
      <Tutorial
        open={tutorialOpen}
        steps={uiContract.tutorial}
        onClose={() => {
          localStorage.setItem("planora_tutorial_seen_v1", "1");
          setTutorialOpen(false);
        }}
        onOpenData={() => navigate("operations")}
        onOpenSchedule={() => navigate("workspace")}
      />
      <div className="toast-stack" aria-live="polite" aria-relevant="additions removals">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast ${toast.kind}`}
            role={toast.kind === "error" ? "alert" : "status"}
          >
            <span className="toast-icon" aria-hidden="true">
              {toast.kind === "error" ? <Warning weight="fill" /> : toast.kind === "success" ? <CheckCircle weight="fill" /> : <Info weight="fill" />}
            </span>
            <span className="toast-copy">
              <strong>{toast.kind === "error" ? "Action needed" : toast.kind === "success" ? "Done" : "Update"}</strong>
              <span>{toast.message}</span>
              {toast.action ? (
                <button type="button" className="toast-action" onClick={() => {
                  toast.action?.onClick();
                  dismissToast(toast.id);
                }}>
                  {toast.action.label}<ArrowRight aria-hidden="true" weight="bold" />
                </button>
              ) : null}
            </span>
            <button
              type="button"
              className="toast-dismiss"
              aria-label="Dismiss notification"
              onClick={() => dismissToast(toast.id)}
            >
              <X aria-hidden="true" weight="bold" />
            </button>
            <span className="toast-progress" aria-hidden="true" />
          </div>
        ))}
      </div>
      {analyticsConsent === "pending" ? (
        <div className="cookie-banner" role="dialog" aria-label="Cookie notice">
          <div>
            <strong>Privacy choices</strong>
            <p>Essential cookies secure sign-in. Optional first-party analytics can be changed anytime.</p>
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
