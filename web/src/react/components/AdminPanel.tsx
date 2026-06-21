import type { Dict, Principal } from "../types";

export function AdminPanel({ principal, auditEvents, system }: { principal: Principal; auditEvents: Dict[]; system: Dict }) {
  if (!principal.is_global_admin) {
    return (
      <section className="panel">
        <h2>Admin</h2>
        <p>This view is only available to global administrators.</p>
      </section>
    );
  }
  return (
    <section className="panel">
      <h2>Global Admin</h2>
      <p className="muted">Admins can inspect all tenants and persisted audit events.</p>
      <div className="metric-grid">
        <div><span>API</span><strong>{system.ok ? "online" : "unknown"}</strong></div>
        <div><span>DB schema</span><strong>{String((system.database as Dict | undefined)?.schema_version ?? "n/a")}</strong></div>
        <div><span>DB path</span><strong>{String((system.database as Dict | undefined)?.path ?? "n/a")}</strong></div>
        <div><span>Audit rows</span><strong>{auditEvents.length}</strong></div>
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
