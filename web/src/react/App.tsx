import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { createApiClient, DEFAULT_PRINCIPAL } from "./api";
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
import type { Dict, Instance, Principal, Schedule, ViewKey } from "./types";

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

export function App() {
  const [apiUrl, setApiUrl] = useState(API_DEFAULT);
  const [principal, setPrincipal] = useState<Principal>(DEFAULT_PRINCIPAL);
  const [token, setToken] = useState("");
  const [view, setView] = useState<ViewKey>("workspace");
  const [presets, setPresets] = useState<string[]>([]);
  const [authConfig, setAuthConfig] = useState<Dict>({});
  const [credentials, setCredentials] = useState({ email: "", password: "", displayName: "", inviteCode: "" });
  const [accessSnapshot, setAccessSnapshot] = useState<Dict>({});
  const [instance, setInstance] = useState<Instance | null>(null);
  const [schedule, setSchedule] = useState<Schedule>({});
  const [sessionId, setSessionId] = useState("");
  const [score, setScore] = useState<Dict>({});
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [projects, setProjects] = useState<Dict[]>([]);
  const [auditEvents, setAuditEvents] = useState<Dict[]>([]);
  const [parity, setParity] = useState<Dict>({});
  const [system, setSystem] = useState<Dict>({});
  const [selectedActivityId, setSelectedActivityId] = useState("");
  const [heldActivityId, setHeldActivityId] = useState("");
  const [moveTargets, setMoveTargets] = useState<Dict[]>([]);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("Ready");

  const api = useMemo(() => createApiClient(apiUrl, principal, token), [apiUrl, principal, token]);

  const refreshBootstrap = useCallback(async () => {
    const authPayload = await api.get<Dict>("/auth/config");
    setAuthConfig(authPayload);
    const whoami = await api.get<Principal>("/auth/whoami");
    const [presetPayload, projectPayload, parityPayload] = await Promise.all([
      api.get<{ presets: string[] }>("/presets"),
      api.get<{ projects: Dict[] }>("/projects"),
      api.get<Dict>("/parity"),
    ]);
    setPrincipal(whoami);
    setPresets(presetPayload.presets || []);
    setProjects(projectPayload.projects || []);
    setParity(parityPayload);
    if (whoami.permissions.includes("audit:read")) {
      const requests: [Promise<{ events: Dict[] }>, Promise<Dict>] = [
        api.get<{ events: Dict[] }>("/audit"),
        api.get<Dict>("/system"),
      ];
      const [audit, systemPayload] = await Promise.all(requests);
      setAuditEvents(audit.events || []);
      setSystem(systemPayload);
    } else {
      setAuditEvents([]);
      setSystem({});
    }
    if (whoami.permissions.includes("access:manage")) {
      setAccessSnapshot(await api.get<Dict>("/access"));
    } else {
      setAccessSnapshot({});
    }
  }, [api]);

  useEffect(() => {
    refreshBootstrap().catch((error: unknown) => setNotice(String(error)));
  }, [refreshBootstrap]);

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
      setNotice(`Loaded ${mode}`);
      setView("workspace");
    } catch (error) {
      setNotice(String(error));
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
    setNotice("Signed in");
  }

  async function register() {
    const payload = await api.post<Dict>("/auth/register", {
      email: credentials.email,
      password: credentials.password,
      display_name: credentials.displayName,
      invite_code: credentials.inviteCode,
    });
    const verificationUrl = payload.verification_url ? ` Dev verification link: ${String(payload.verification_url)}` : "";
    setNotice(`Registration created. Check your email to confirm the account.${verificationUrl}`);
  }

  async function applyAccessChange(change: Dict) {
    const next = await api.post<Dict>("/access", change);
    setAccessSnapshot(next);
    setNotice("Access settings updated");
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
      setConflicts((result.hard_conflicts || []) as string[]);
      setScore(((result.meta as Dict)?.quality || {}) as Dict);
      setNotice("Solve complete");
    } catch (error) {
      setNotice(String(error));
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
      setConflicts((result.hard_conflicts || []) as string[]);
      setNotice("Score recalculated");
    } catch (error) {
      setNotice(String(error));
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
      setNotice("Improve complete");
    } catch (error) {
      setNotice(String(error));
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
    setNotice(`Background improve job ${String(payload.job_id || "")} started`);
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
    setNotice(`Previewing move targets for A${selectedActivityId}`);
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
    setNotice("Moved activity");
  }

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

      <div className="dashboard-grid">
        <LoginPanel
          principal={principal}
          authConfig={authConfig}
          credentials={credentials}
          onPrincipalChange={setPrincipal}
          onLogin={() => login().catch((error: unknown) => setNotice(String(error)))}
          onRegister={() => register().catch((error: unknown) => setNotice(String(error)))}
          onCredentialsChange={setCredentials}
        />
        <OperationsPanel
          instance={instance}
          presets={presets}
          busy={busy}
          settings={settings}
          onLoadPreset={loadPreset}
          onSolve={solve}
          onImprove={improve}
          onScore={scoreCurrent}
          onStartImproveJob={() => startImproveJob().catch((error: unknown) => setNotice(String(error)))}
        />
      </div>

      <RunSummary score={score} conflicts={conflicts} />

      <ScheduleBoard
        instance={instance}
        schedule={schedule}
        selectedWeek={selectedWeek}
        targets={moveTargets}
        heldActivityId={heldActivityId}
        selectedActivityId={selectedActivityId}
        onWeekChange={setSelectedWeek}
        onSelectActivity={setSelectedActivityId}
        onHold={() => holdSelected().catch((error: unknown) => setNotice(String(error)))}
        onRelease={() => {
          setHeldActivityId("");
          setMoveTargets([]);
          setNotice("Hold released");
        }}
        onMoveTarget={(day, slot) => moveTarget(day, slot).catch((error: unknown) => setNotice(String(error)))}
      />
    </div>
  );

  const content = {
    workspace: workspaceContent,
    review: <ReviewPanel conflicts={conflicts} score={score} />,
    operations: (
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
          onStartImproveJob={() => startImproveJob().catch((error: unknown) => setNotice(String(error)))}
        />
        <RunSummary score={score} conflicts={conflicts} />
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
    projects: <ProjectsPanel projects={projects} onRefresh={() => refreshBootstrap().catch((error: unknown) => setNotice(String(error)))} />,
    parity: <ParityPanel manifest={parity} />,
    access: <AccessPanel principal={principal} snapshot={accessSnapshot} onChange={applyAccessChange} />,
    admin: <AdminPanel principal={principal} auditEvents={auditEvents} system={system} />,
  } as Record<ViewKey, ReactNode>;

  return (
    <AppShell
      principal={principal}
      apiUrl={apiUrl}
      activeView={view}
      onApiUrlChange={setApiUrl}
      onViewChange={setView}
    >
      <div className="notice">{notice}</div>
      {content[view]}
    </AppShell>
  );
}
