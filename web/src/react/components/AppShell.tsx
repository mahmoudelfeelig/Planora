import type { Principal, ViewKey } from "../types";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

const AUTH_VIEWS: Array<{
  key: ViewKey;
  label: string;
  description: string;
  adminOnly?: boolean;
  permission?: string;
}> = [
  { key: "workspace", label: "Schedule", description: "Timetable workspace" },
  { key: "operations", label: "Solver", description: "Generate and improve" },
  { key: "settings", label: "Solver settings", description: "Search and runtime" },
  { key: "projects", label: "Projects", description: "Saved workspaces" },
  { key: "review", label: "Diagnostics", description: "Conflicts and quality" },
  { key: "fairness", label: "Insights", description: "Workload and fairness" },
  { key: "parity", label: "Platform", description: "Feature coverage" },
  { key: "account", label: "Organizations", description: "Membership and profile" },
  { key: "access", label: "People", description: "Users and access", permission: "access:manage" },
  { key: "admin", label: "Administration", description: "System operations", adminOnly: true },
];

const PUBLIC_VIEWS: Array<{ key: ViewKey; label: string }> = [
  { key: "home", label: "Home" },
  { key: "faq", label: "FAQ" },
  { key: "privacy", label: "Privacy" },
];

function NavIcon({ view }: { view: ViewKey }) {
  const paths: Partial<Record<ViewKey, ReactNode>> = {
    workspace: <><rect x="3" y="4" width="18" height="17" rx="3" /><path d="M8 2v4M16 2v4M3 9h18M8 13h3M14 13h2M8 17h2" /></>,
    operations: <><path d="m13 2-9 12h7l-1 8 9-12h-7l1-8Z" /></>,
    settings: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></>,
    projects: <><path d="M3 6.5h7l2 2h9v10.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6.5Z" /><path d="M3 10h18" /></>,
    review: <><path d="M4 19V5M4 19h16" /><path d="m7 15 4-4 3 2 5-6" /></>,
    fairness: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
    parity: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><path d="M14 17.5h7M17.5 14v7" /></>,
    account: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
    access: <><circle cx="9" cy="8" r="3" /><path d="M3 19a6 6 0 0 1 12 0M17 8h4M19 6v4" /></>,
    admin: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>,
  };
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[view]}</svg>;
}

type Props = {
  principal: Principal;
  activeView: ViewKey;
  authenticated: boolean;
  theme: "light" | "dark";
  analyticsConsent: "pending" | "granted" | "denied";
  onViewChange(view: ViewKey): void;
  onSignOut(): void;
  onThemeToggle(): void;
  onAnalyticsConsentChange(consent: "pending" | "granted" | "denied"): void;
  children: ReactNode;
};

export function AppShell({
  principal,
  activeView,
  authenticated,
  theme,
  analyticsConsent,
  onViewChange,
  onSignOut,
  onThemeToggle,
  onAnalyticsConsentChange,
  children,
}: Props) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const visibleViews = AUTH_VIEWS.filter((view) =>
    (!view.adminOnly || principal.is_global_admin) &&
    (!view.permission || principal.permissions.includes(view.permission)),
  );
  const activeItem = AUTH_VIEWS.find((view) => view.key === activeView);
  const displayName = principal.user_id.replace(/^email:/, "").split("@")[0] || "Account";
  const roleLabel = principal.role.replaceAll("_", " ");

  useEffect(() => {
    setMobileNavOpen(false);
  }, [activeView]);

  const changeView = (view: ViewKey) => {
    setMobileNavOpen(false);
    onViewChange(view);
  };

  return (
    <div className={`app-frame ${authenticated ? "authenticated-frame" : "public-frame"}`}>
      <header className="site-nav">
        <button type="button" className="brand-link" onClick={() => changeView(authenticated ? "workspace" : "home")} aria-label="Planora home">
          <img src="/app-icon.png" alt="" />
          <span className="brand-wordmark">
            <strong>Planora</strong>
            {authenticated ? <small>Academic scheduling</small> : null}
          </span>
        </button>
        {authenticated ? (
          <div className="nav-page-context" aria-live="polite">
            <span>Workspace</span>
            <strong>{activeItem?.label || "Planora"}</strong>
          </div>
        ) : (
          <nav className="public-nav-links" aria-label="Main navigation">
            {PUBLIC_VIEWS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={activeView === item.key ? "active" : ""}
                onClick={() => changeView(item.key)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        )}
        <div className="nav-actions">
          <button type="button" className="theme-toggle icon-button" onClick={onThemeToggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 3v2.2M12 18.8V21M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M3 12h2.2M18.8 12H21M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" />
                <circle cx="12" cy="12" r="4.2" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M20.1 14.4A7.5 7.5 0 0 1 9.6 3.9 8.8 8.8 0 1 0 20.1 14.4Z" />
              </svg>
            )}
          </button>
          {authenticated ? (
            <>
              <div className="header-profile" title={`${principal.user_id} · ${principal.tenant_id}`}>
                <span>{displayName.slice(0, 1).toUpperCase()}</span>
                <div>
                  <strong>{displayName}</strong>
                  <small>{roleLabel}</small>
                </div>
              </div>
              <button
                type="button"
                className={`mobile-nav-toggle icon-button ${mobileNavOpen ? "active" : ""}`}
                aria-label="Toggle workspace navigation"
                aria-expanded={mobileNavOpen}
                onClick={() => setMobileNavOpen((open) => !open)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
              </button>
            </>
          ) : (
            <button type="button" className={activeView === "login" ? "active nav-auth-button" : "nav-auth-button"} onClick={() => changeView("login")}>Sign in</button>
          )}
        </div>
      </header>
      <div className="app-body">
        {authenticated ? (
          <>
            <button
              type="button"
              className={`nav-scrim ${mobileNavOpen ? "visible" : ""}`}
              aria-label="Close workspace navigation"
              onClick={() => setMobileNavOpen(false)}
            />
            <aside className={`workspace-sidebar ${mobileNavOpen ? "open" : ""}`}>
              <nav className="workspace-nav" aria-label="Workspace navigation">
                {visibleViews.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={activeView === item.key ? "active" : ""}
                    aria-current={activeView === item.key ? "page" : undefined}
                    onClick={() => changeView(item.key)}
                  >
                    <NavIcon view={item.key} />
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  </button>
                ))}
              </nav>
              <div className="sidebar-account">
                <div>
                  <span className="account-avatar">{displayName.slice(0, 1).toUpperCase()}</span>
                  <span>
                    <strong>{displayName}</strong>
                    <small>{principal.tenant_id}</small>
                  </span>
                </div>
                <button type="button" className="sidebar-signout" onClick={onSignOut}>Sign out</button>
              </div>
            </aside>
          </>
        ) : null}
        <main className="page-content">{children}</main>
      </div>
      <footer className="site-footer">
        <a className="github-link" href="https://github.com/mahmoudelfeelig/Scheduler" target="_blank" rel="noreferrer" aria-label="Planora GitHub repository">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M12 2C6.48 2 2 6.59 2 12.26c0 4.53 2.87 8.37 6.84 9.73.5.09.68-.22.68-.49 0-.24-.01-1.04-.01-1.89-2.78.62-3.37-1.22-3.37-1.22-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.63.07-.63 1 .07 1.53 1.06 1.53 1.06.9 1.58 2.35 1.12 2.92.86.09-.67.35-1.12.63-1.38-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05A9.34 9.34 0 0 1 12 6.99c.85 0 1.7.12 2.5.35 1.91-1.33 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.81-4.57 5.06.36.32.68.94.68 1.9 0 1.37-.01 2.47-.01 2.8 0 .27.18.59.69.49A10.23 10.23 0 0 0 22 12.26C22 6.59 17.52 2 12 2Z" />
          </svg>
          Repository
        </a>
        <button
          type="button"
          className="footer-link-button"
          onClick={() => onAnalyticsConsentChange(analyticsConsent === "granted" ? "denied" : "granted")}
        >
          Analytics: {analyticsConsent === "granted" ? "On" : "Off"}
        </button>
        <button type="button" className="footer-link-button" onClick={() => changeView("privacy")}>
          Privacy
        </button>
        <button type="button" className="footer-link-button" onClick={() => changeView("faq")}>
          FAQ
        </button>
        <span>© Mahmoud Elfeel</span>
      </footer>
    </div>
  );
}
