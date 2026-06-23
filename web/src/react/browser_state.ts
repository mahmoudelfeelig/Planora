export type ThemeMode = "light" | "dark";
export type AnalyticsConsent = "pending" | "granted" | "denied";

export function readStoredTheme(): ThemeMode {
  const stored = localStorage.getItem("planora_theme");
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function readAnalyticsConsent(): AnalyticsConsent {
  const stored = localStorage.getItem("planora_analytics_consent");
  return stored === "granted" || stored === "denied" ? stored : "pending";
}

export function setCookie(name: string, value: string, maxAgeSeconds: number) {
  document.cookie = `${name}=${encodeURIComponent(value)}; Max-Age=${maxAgeSeconds}; Path=/; SameSite=Lax`;
}

export function clearCookie(name: string) {
  document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
}

export function analyticsClientId(): string {
  const existing = localStorage.getItem("planora_analytics_id");
  if (existing) return existing;
  const next = crypto.randomUUID();
  localStorage.setItem("planora_analytics_id", next);
  setCookie("planora_analytics", next, 60 * 60 * 24 * 365);
  return next;
}
