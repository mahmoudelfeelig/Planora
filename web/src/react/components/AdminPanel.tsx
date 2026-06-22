import type { Dict, Principal } from "../types";
import { useState } from "react";

function rows(value: unknown): Dict[] {
  return Array.isArray(value) ? (value as Dict[]) : [];
}

function asDict(value: unknown): Dict {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Dict) : {};
}

function asNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatBytes(value: unknown): string {
  const bytes = asNumber(value);
  if (bytes === null) return "n/a";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let scaled = bytes;
  let index = 0;
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  return `${scaled >= 10 || index === 0 ? scaled.toFixed(0) : scaled.toFixed(1)} ${units[index]}`;
}

function formatPercent(value: unknown): string {
  const percent = asNumber(value);
  return percent === null ? "n/a" : `${percent.toFixed(percent >= 10 ? 0 : 1)}%`;
}

function formatDuration(seconds: unknown): string {
  const total = asNumber(seconds);
  if (total === null) return "n/a";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function UsageBar({ label, percent, detail }: { label: string; percent: unknown; detail: string }) {
  const value = Math.max(0, Math.min(100, asNumber(percent) ?? 0));
  const state = value >= 90 ? "danger" : value >= 75 ? "warn" : "ok";
  return (
    <div className="usage-row">
      <div className="usage-row-header">
        <span>{label}</span>
        <strong>{formatPercent(percent)}</strong>
      </div>
      <div className={`usage-track ${state}`} aria-label={`${label} ${formatPercent(percent)}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}>
        <span style={{ width: `${value}%` }} />
      </div>
      <small>{detail}</small>
    </div>
  );
}

export function AdminPanel({
  principal,
  auditEvents,
  system,
  systemStatus,
  analytics,
  onRefresh,
  onEmailTest,
  onDownload,
}: {
  principal: Principal;
  auditEvents: Dict[];
  system: Dict;
  systemStatus: Dict;
  analytics: Dict;
  onRefresh(filters: Dict): Promise<void>;
  onEmailTest(email: string): Promise<void>;
  onDownload(path: string, filename: string): Promise<void>;
}) {
  const [filters, setFilters] = useState({ days: "30", tenant_id: "", event_name: "", path: "", action: "", user_id: "" });
  const [email, setEmail] = useState("");
  if (!principal.is_global_admin) {
    return (
      <section className="panel">
        <h2>Admin</h2>
        <p>This view is only available to global administrators.</p>
      </section>
    );
  }
  const topPaths = rows(analytics.top_paths);
  const topEvents = rows(analytics.top_events);
  const byDay = rows(analytics.by_day);
  const statusApi = asDict(systemStatus.api);
  const disk = asDict(systemStatus.disk);
  const memory = asDict(systemStatus.memory);
  const containerMemory = asDict(memory.container);
  const hostMemory = asDict(memory.host);
  const jobs = asDict(systemStatus.jobs);
  const netdata = asDict(systemStatus.netdata);
  const netdataUrl = String(netdata.url || "");
  return (
    <section className="panel">
      <h2>Global Admin</h2>
      <p className="muted">Admins can inspect all tenants, audit events, and consented first-party product analytics.</p>
      <div className="metric-grid">
        <div><span>API</span><strong>{system.ok ? "online" : "unknown"}</strong></div>
        <div><span>DB schema</span><strong>{String((system.database as Dict | undefined)?.schema_version ?? "n/a")}</strong></div>
        <div><span>DB path</span><strong>{String((system.database as Dict | undefined)?.path ?? "n/a")}</strong></div>
        <div><span>Audit rows</span><strong>{auditEvents.length}</strong></div>
        <div><span>Analytics events</span><strong>{String(analytics.events ?? 0)}</strong></div>
        <div><span>Analytics visitors</span><strong>{String(analytics.visitors ?? 0)}</strong></div>
      </div>

      <div className="subpanel">
        <div className="section-header">
          <div>
            <h3>Runtime Status</h3>
            <p className="section-copy">Fast local health signals from the API container and SQLite data volume. Use Netdata for full host and Docker charts.</p>
          </div>
          {netdataUrl ? (
            <a className="secondary-link-button" href={netdataUrl} target="_blank" rel="noreferrer">Open Netdata</a>
          ) : null}
        </div>
        <div className="metric-grid">
          <div><span>API uptime</span><strong>{formatDuration(statusApi.uptime_seconds)}</strong></div>
          <div><span>Mode</span><strong>{statusApi.production ? "production" : "development"}</strong></div>
          <div><span>DB size</span><strong>{formatBytes((systemStatus.database as Dict | undefined)?.size_bytes)}</strong></div>
          <div><span>Jobs active</span><strong>{String(jobs.active ?? 0)} / {String(jobs.active_limit_per_tenant ?? "n/a")}</strong></div>
        </div>
        <div className="status-grid">
          <UsageBar
            label="Data volume disk"
            percent={disk.used_percent}
            detail={`${formatBytes(disk.used_bytes)} used, ${formatBytes(disk.free_bytes)} free`}
          />
          <UsageBar
            label="API container memory"
            percent={containerMemory.used_percent}
            detail={`${formatBytes(containerMemory.used_bytes)} used of ${formatBytes(containerMemory.limit_bytes)}`}
          />
          <UsageBar
            label="Host memory"
            percent={hostMemory.used_percent}
            detail={`${formatBytes(hostMemory.used_bytes)} used, ${formatBytes(hostMemory.available_bytes)} available`}
          />
        </div>
      </div>

      <div className="subpanel">
        <h3>Filters & Exports</h3>
        <div className="identity-grid access-controls">
          <label>Days<input value={filters.days} onChange={(event) => setFilters({ ...filters, days: event.target.value })} inputMode="numeric" /></label>
          <label>Tenant<input value={filters.tenant_id} onChange={(event) => setFilters({ ...filters, tenant_id: event.target.value })} placeholder="All tenants" /></label>
          <label>Event<input value={filters.event_name} onChange={(event) => setFilters({ ...filters, event_name: event.target.value })} placeholder="page_view" /></label>
          <label>Path<input value={filters.path} onChange={(event) => setFilters({ ...filters, path: event.target.value })} placeholder="/workspace" /></label>
          <label>Audit action<input value={filters.action} onChange={(event) => setFilters({ ...filters, action: event.target.value })} placeholder="auth.login" /></label>
          <label>Audit user<input value={filters.user_id} onChange={(event) => setFilters({ ...filters, user_id: event.target.value })} placeholder="email:user@example.edu" /></label>
          <button type="button" onClick={() => void onRefresh(filters)}>Apply filters</button>
          <button type="button" onClick={() => void onDownload(`/analytics/export.csv?${new URLSearchParams(filters).toString()}`, "planora-analytics.csv")}>Export analytics CSV</button>
          <button type="button" className="secondary-button" onClick={() => void onDownload(`/audit.csv?${new URLSearchParams(filters).toString()}`, "planora-audit.csv")}>Export audit CSV</button>
        </div>
      </div>

      <div className="subpanel">
        <h3>Email Deliverability</h3>
        <p className="section-copy">Use this after configuring Brevo SPF, DKIM, and DMARC to test real inbox delivery.</p>
        <div className="identity-grid access-controls">
          <label>Recipient<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="admin@example.edu" /></label>
          <button type="button" disabled={!email.includes("@")} onClick={() => void onEmailTest(email)}>Send test email</button>
        </div>
      </div>

      <div className="split-grid">
        <div className="subpanel">
          <h3>Top Pages</h3>
          <div className="table-like compact">
            <div className="table-row header"><span>Path</span><span>Events</span><span>Visitors</span></div>
            {topPaths.length ? topPaths.map((row) => (
              <div className="table-row" key={String(row.path)}>
                <span>{String(row.path)}</span>
                <span>{String(row.events)}</span>
                <span>{String(row.visitors)}</span>
              </div>
            )) : <div className="empty-row">No page analytics yet.</div>}
          </div>
        </div>
        <div className="subpanel">
          <h3>Top Events</h3>
          <div className="table-like compact">
            <div className="table-row header"><span>Event</span><span>Count</span><span>Window</span></div>
            {topEvents.length ? topEvents.map((row) => (
              <div className="table-row" key={String(row.event_name)}>
                <span>{String(row.event_name)}</span>
                <span>{String(row.events)}</span>
                <span>{String(analytics.days ?? 30)} days</span>
              </div>
            )) : <div className="empty-row">No event analytics yet.</div>}
          </div>
        </div>
      </div>

      <div className="subpanel">
        <h3>Daily Traffic</h3>
        <div className="table-like compact">
          <div className="table-row header"><span>Day</span><span>Events</span><span>Visitors</span></div>
          {byDay.length ? byDay.map((row) => (
            <div className="table-row" key={String(row.day)}>
              <span>{String(row.day)}</span>
              <span>{String(row.events)}</span>
              <span>{String(row.visitors)}</span>
            </div>
          )) : <div className="empty-row">No daily analytics yet.</div>}
        </div>
      </div>

      <div className="table-like">
        <div className="table-row header"><span>Action</span><span>Tenant</span><span>User</span></div>
        {auditEvents.length ? auditEvents.map((event) => (
          <div className="table-row" key={String(event.id)}>
            <span>{String(event.action)}</span>
            <span>{String(event.tenant_id)}</span>
            <span>{String(event.user_id)}</span>
          </div>
        )) : <div className="empty-row">No audit events yet.</div>}
      </div>
    </section>
  );
}
