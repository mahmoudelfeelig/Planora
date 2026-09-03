from __future__ import annotations

import math
import os
import time
from http.server import BaseHTTPRequestHandler
from ipaddress import ip_address
from threading import Lock
from typing import Callable
from urllib.parse import urlparse

from services.auth_service import Principal
from services.env_service import env_bool_strict


class RateLimitExceeded(PermissionError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Rate limit exceeded. Please retry shortly.")
        self.retry_after = max(1, int(retry_after))


def _normalized_ip(value: str) -> str:
    try:
        return str(ip_address(str(value).strip()))
    except ValueError:
        return ""


def rate_limit_identity(
    handler: BaseHTTPRequestHandler,
    principal_from_headers: Callable[[object], Principal],
) -> tuple[str, bool]:
    try:
        principal = principal_from_headers(handler.headers)
        return f"user:{principal.tenant_id}:{principal.user_id}", True
    except Exception:
        client = _normalized_ip(str(handler.client_address[0])) or str(handler.client_address[0])
        if env_bool_strict("PLANORA_TRUST_PROXY_HEADERS", False):
            forwarded = [
                part.strip()
                for part in str(handler.headers.get("X-Forwarded-For", "") or "").split(",")
                if part.strip()
            ]
            if forwarded:
                client = _normalized_ip(forwarded[-1]) or client
        return f"ip:{client}", False


def check_rate_limit(
    handler: BaseHTTPRequestHandler,
    *,
    buckets: dict[str, list[float]],
    lock: Lock,
    principal_from_headers: Callable[[object], Principal],
) -> None:
    path = urlparse(handler.path).path
    if path in {"/health", "/ready"}:
        return
    identity, authenticated = rate_limit_identity(handler, principal_from_headers)
    sensitive_auth_paths = {
        "/auth/login", "/auth/register", "/auth/forgot-password",
        "/auth/reset-password", "/auth/verify", "/auth/verify-email",
        "/auth/resend-verification", "/access/join-invite",
    }
    if path in sensitive_auth_paths:
        category = "auth-sensitive"
        limit = int(os.environ.get("PLANORA_RATE_LIMIT_AUTH_PER_MINUTE", "20"))
    elif path in {"/analytics/event", "/events/collect"}:
        category = "telemetry"
        limit = int(os.environ.get("PLANORA_RATE_LIMIT_TELEMETRY_PER_MINUTE", "600"))
    elif authenticated:
        category = "authenticated"
        limit = int(os.environ.get("PLANORA_RATE_LIMIT_AUTHENTICATED_PER_MINUTE", "1200"))
    else:
        category = "anonymous"
        limit = int(os.environ.get(
            "PLANORA_RATE_LIMIT_ANONYMOUS_PER_MINUTE",
            os.environ.get("PLANORA_RATE_LIMIT_PER_MINUTE", "120"),
        ))
    if limit <= 0:
        return
    now = time.monotonic()
    with lock:
        max_buckets = max(1, int(os.environ.get("PLANORA_RATE_LIMIT_MAX_BUCKETS", "4096")))
        bucket_key = f"{identity}:{category}"
        if bucket_key not in buckets and len(buckets) >= max_buckets:
            stale_keys = [key for key, stamps in buckets.items() if not stamps or now - stamps[-1] >= 60.0]
            for key in stale_keys:
                buckets.pop(key, None)
        if bucket_key not in buckets and len(buckets) >= max_buckets:
            bucket_key = f"overflow:{category}"
            if bucket_key not in buckets:
                while len(buckets) >= max_buckets:
                    buckets.pop(next(iter(buckets)))
        recent = [stamp for stamp in buckets.get(bucket_key, []) if now - stamp < 60.0]
        if len(recent) >= limit:
            retry_after = math.ceil(60.0 - (now - recent[0])) if recent else 1
            raise RateLimitExceeded(retry_after)
        recent.append(now)
        buckets[bucket_key] = recent
