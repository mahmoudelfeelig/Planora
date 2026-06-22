import type { Dict, Principal } from "./types";

export type ApiClient = {
  baseUrl: string;
  principal: Principal;
  token: string;
  get<T = Dict>(path: string): Promise<T>;
  post<T = Dict>(path: string, payload?: Dict): Promise<T>;
  delete<T = Dict>(path: string): Promise<T>;
  download(path: string, fallbackFilename: string): Promise<void>;
};

export class ApiError extends Error {
  status: number;
  retryAfter: number | null;

  constructor(message: string, status: number, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

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
  let response: Response;
  const target = `${baseUrl.replace(/\/$/, "")}${path}`;
  try {
    response = await fetch(target, {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(principal, token),
        ...(init.method && init.method !== "GET" && csrfToken() ? { "X-CSRF-Token": csrfToken() } : {}),
        ...(init.headers || {}),
      },
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Cannot reach the Planora API at ${baseUrl}. Start the backend on http://127.0.0.1:8787 for local development, or set VITE_PLANORA_API_URL. (${detail})`,
    );
  }
  let payload: Dict = {};
  try {
    payload = await response.json();
  } catch {
    payload = { error: response.statusText || `HTTP ${response.status}` };
  }
  if (!response.ok || payload.error) {
    const retryHeader = Number(response.headers.get("Retry-After"));
    const retryPayload = Number(payload.retry_after);
    const retryAfter = Number.isFinite(retryHeader) && retryHeader > 0
      ? retryHeader
      : Number.isFinite(retryPayload) && retryPayload > 0 ? retryPayload : null;
    throw new ApiError(String(payload.error || response.statusText), response.status, retryAfter);
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
    delete: (path) => requestJson(baseUrl, principal, token, path, { method: "DELETE" }),
    download: async (path, fallbackFilename) => {
      const response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
        credentials: "include",
        headers: authHeaders(principal, token),
      });
      if (!response.ok) {
        throw new ApiError(`Download failed: ${response.statusText || response.status}`, response.status);
      }
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^";]+)"?/i);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = match?.[1] || fallbackFilename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    },
  };
}

export const DEFAULT_PRINCIPAL: Principal = {
  user_id: "local-admin",
  role: "admin",
  tenant_id: "default",
  permissions: [],
  is_global_admin: true,
};
