import type { Principal, ViewKey } from "../types";
import type { ReactNode } from "react";

const AUTH_VIEW_GROUPS: Array<{
  label: string;
  views: Array<{ key: ViewKey; label: string; adminOnly?: boolean; permission?: string }>;
}> = [
  {
    label: "Plan",
    views: [
      { key: "workspace", label: "Schedule" },
      { key: "operations", label: "Solve" },
      { key: "projects", label: "Projects" },
    ],
  },
  {
    label: "Review",
    views: [
      { key: "review", label: "Diagnostics" },
      { key: "fairness", label: "Insights" },
      { key: "parity", label: "Platform" },
    ],
  },
  {
    label: "Account",
    views: [
      { key: "account", label: "My Groups" },
      { key: "access", label: "Users", permission: "access:manage" },
      { key: "admin", label: "Admin", adminOnly: true },
    ],
  },
];

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
  const visibleGroups = AUTH_VIEW_GROUPS.map((group) => ({
    ...group,
    views: group.views.filter((view) =>
      (!view.adminOnly || principal.is_global_admin) &&
      (!view.permission || principal.permissions.includes(view.permission)),
    ),
  })).filter((group) => group.views.length > 0);

  return (
    <div className="app-frame">
      <header className="site-nav">
        <button type="button" className="brand-link" onClick={() => onViewChange("home")} aria-label="Planora home">
          <img src="/app-icon.png" alt="" />
          <span>Planora</span>
        </button>
        <nav className="top-links" aria-label="Main navigation">
          {authenticated
            ? visibleGroups.map((group) => (
                <div className="nav-cluster" key={group.label}>
                  <span>{group.label}</span>
                  {group.views.map((view) => (
                    <button
                      key={view.key}
                      type="button"
                      className={activeView === view.key ? "active" : ""}
                      onClick={() => onViewChange(view.key)}
                    >
                      {view.label}
                    </button>
                  ))}
                </div>
              ))
            : null}
        </nav>
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
              <button type="button" className="secondary-button nav-auth-button" onClick={onSignOut}>Sign out</button>
            </>
          ) : (
            <button type="button" className={activeView === "login" ? "active nav-auth-button" : "nav-auth-button"} onClick={() => onViewChange("login")}>Login</button>
          )}
        </div>
      </header>
      <main className="page-content">{children}</main>
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
        <button type="button" className="footer-link-button" onClick={() => onViewChange("privacy")}>
          Privacy
        </button>
        <button type="button" className="footer-link-button" onClick={() => onViewChange("faq")}>
          FAQ
        </button>
        <span>© Mahmoud Elfeel</span>
      </footer>
    </div>
  );
}
