import type { Dict, Principal } from "./types";

export type ApiClient = {
  baseUrl: string;
  principal: Principal;
  token: string;
  get<T = Dict>(path: string): Promise<T>;
  post<T = Dict>(path: string, payload?: Dict): Promise<T>;
};

function authHeaders(principal: Principal, token = ""): HeadersInit {
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {
    "X-Planora-User": principal.user_id,
    "X-Planora-Role": principal.role,
    "X-Planora-Tenant": principal.tenant_id,
  };
}

function csrfToken(): string {
  const prefix = "planora_csrf=";
  const row = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix));
  return row ? decodeURIComponent(row.slice(prefix.length)) : "";
}

async function requestJson<T>(
  baseUrl: string,
  principal: Principal,
  token: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(principal, token),
      ...(init.method && init.method !== "GET" && csrfToken() ? { "X-CSRF-Token": csrfToken() } : {}),
      ...(init.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(String(payload.error || response.statusText));
  }
  return payload as T;
}

export function createApiClient(baseUrl: string, principal: Principal, token = ""): ApiClient {
  return {
    baseUrl,
    principal,
    token,
    get: (path) => requestJson(baseUrl, principal, token, path),
    post: (path, payload = {}) =>
      requestJson(baseUrl, principal, token, path, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  };
}

export const DEFAULT_PRINCIPAL: Principal = {
  user_id: "local-admin",
  role: "admin",
  tenant_id: "default",
  permissions: [],
  is_global_admin: true,
};
