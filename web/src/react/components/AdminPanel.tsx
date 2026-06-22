import type { Dict, Principal } from "../types";
import { useState } from "react";

function rows(value: unknown): Dict[] {
  return Array.isArray(value) ? (value as Dict[]) : [];
}

export function AdminPanel({
  principal,
  auditEvents,
  system,
  analytics,
  onRefresh,
  onEmailTest,
  apiBaseUrl = "",
}: {
  principal: Principal;
  auditEvents: Dict[];
  system: Dict;
  analytics: Dict;
  onRefresh(filters: Dict): Promise<void>;
  onEmailTest(email: string): Promise<void>;
  apiBaseUrl?: string;
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
        <h3>Filters & Exports</h3>
        <div className="identity-grid access-controls">
          <label>Days<input value={filters.days} onChange={(event) => setFilters({ ...filters, days: event.target.value })} inputMode="numeric" /></label>
          <label>Tenant<input value={filters.tenant_id} onChange={(event) => setFilters({ ...filters, tenant_id: event.target.value })} placeholder="All tenants" /></label>
          <label>Event<input value={filters.event_name} onChange={(event) => setFilters({ ...filters, event_name: event.target.value })} placeholder="page_view" /></label>
          <label>Path<input value={filters.path} onChange={(event) => setFilters({ ...filters, path: event.target.value })} placeholder="/workspace" /></label>
          <label>Audit action<input value={filters.action} onChange={(event) => setFilters({ ...filters, action: event.target.value })} placeholder="auth.login" /></label>
          <label>Audit user<input value={filters.user_id} onChange={(event) => setFilters({ ...filters, user_id: event.target.value })} placeholder="email:user@example.edu" /></label>
          <button type="button" onClick={() => void onRefresh(filters)}>Apply filters</button>
          <a className="button-link" href={`${apiBaseUrl}/analytics/export.csv?${new URLSearchParams(filters).toString()}`}>Export analytics CSV</a>
          <a className="button-link secondary" href={`${apiBaseUrl}/audit.csv?${new URLSearchParams(filters).toString()}`}>Export audit CSV</a>
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
