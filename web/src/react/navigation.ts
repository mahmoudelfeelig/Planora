import type { ViewKey } from "./types";

export const VIEW_PATHS: Record<ViewKey, string> = {
  home: "/",
  faq: "/faq",
  privacy: "/privacy",
  login: "/login",
  account: "/account",
  workspace: "/workspace",
  operations: "/runs",
  review: "/diagnostics",
  settings: "/settings",
  fairness: "/insights",
  projects: "/projects",
  parity: "/platform",
  access: "/access",
  admin: "/admin",
};

const PATH_VIEWS: Record<string, ViewKey> = Object.fromEntries(
  Object.entries(VIEW_PATHS).map(([key, path]) => [path, key as ViewKey]),
) as Record<string, ViewKey>;

export function viewFromLocation(): ViewKey {
  return PATH_VIEWS[window.location.pathname] || "workspace";
}
