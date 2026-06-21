import type { Principal, ViewKey } from "../types";
import type { ReactNode } from "react";

const VIEWS: Array<{ key: ViewKey; label: string; adminOnly?: boolean; permission?: string }> = [
  { key: "workspace", label: "Workspace" },
  { key: "review", label: "Diagnostics" },
  { key: "operations", label: "Automation" },
  { key: "settings", label: "Settings" },
  { key: "fairness", label: "Insights" },
  { key: "projects", label: "Projects" },
  { key: "parity", label: "Platform" },
  { key: "access", label: "Access", permission: "access:manage" },
  { key: "admin", label: "Admin", adminOnly: true },
];

type Props = {
  principal: Principal;
  apiUrl: string;
  activeView: ViewKey;
  onApiUrlChange(value: string): void;
  onViewChange(view: ViewKey): void;
  children: ReactNode;
};

export function AppShell({
  principal,
  apiUrl,
  activeView,
  onApiUrlChange,
  onViewChange,
  children,
}: Props) {
  const visibleViews = VIEWS.filter((view) =>
    (!view.adminOnly || principal.is_global_admin) &&
    (!view.permission || principal.permissions.includes(view.permission)),
  );
  return (
    <div className="app-frame">
      <header className="app-header">
        <div className="brand">
          <img src="/app-icon.png" alt="Planora" />
          <div>
            <strong>Planora Academic Scheduler</strong>
            <span>{principal.tenant_id} · {principal.role} · {principal.user_id}</span>
          </div>
        </div>
        <label className="api-field">
          API endpoint
          <input value={apiUrl} onChange={(event) => onApiUrlChange(event.target.value)} />
        </label>
      </header>
      <div className="app-layout">
        <nav className="navigation-rail" aria-label="Primary">
          {visibleViews.map((view) => (
            <button
              key={view.key}
              className={view.key === activeView ? "active" : ""}
              type="button"
              onClick={() => onViewChange(view.key)}
            >
              {view.label}
            </button>
          ))}
        </nav>
        <main className="content-pane">{children}</main>
      </div>
    </div>
  );
}
