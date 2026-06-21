from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from services.env_service import env_bool, env_value


_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class OutboundEmail:
    to_email: str
    subject: str
    body: str


def normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise ValueError("A valid email address is required.")
    return normalized


def validate_password(password: str) -> None:
    if len(str(password or "")) < 10:
        raise ValueError("Password must be at least 10 characters.")


def hash_password(password: str) -> str:
    validate_password(password)
    return _PASSWORD_HASHER.hash(str(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(_PASSWORD_HASHER.verify(password_hash, str(password or "")))
    except (VerifyMismatchError, VerificationError, TypeError):
        return False


def should_rehash_password(password_hash: str) -> bool:
    try:
        return bool(_PASSWORD_HASHER.check_needs_rehash(password_hash))
    except Exception:
        return True


def new_plain_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(24)}"


def secret_pepper() -> str:
    return env_value("PLANORA_TOKEN_PEPPER", env_value("PLANORA_AUTH_SECRET", "planora-local-token-pepper"))


def hash_token(token: str) -> str:
    digest = hmac.new(secret_pepper().encode("utf-8"), str(token).encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def email_verification_required() -> bool:
    return env_bool("PLANORA_EMAIL_VERIFICATION_REQUIRED", True)


def registration_enabled() -> bool:
    return env_bool("PLANORA_REGISTRATION_ENABLED", True)


def smtp_configured() -> bool:
    return bool(env_value("PLANORA_SMTP_HOST", ""))


def verification_base_url(default_base_url: str) -> str:
    configured = env_value("PLANORA_PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or default_base_url.rstrip("/")


def build_verification_email(base_url: str, to_email: str, token: str) -> OutboundEmail:
    url = f"{base_url}/auth/verify?token={token}"
    return OutboundEmail(
        to_email=to_email,
        subject="Confirm your Planora account",
        body=(
            "Confirm your Planora account by opening this link:\n\n"
            f"{url}\n\n"
            "If you did not register for Planora, ignore this email."
        ),
    )


def send_email(message: OutboundEmail) -> None:
    host = env_value("PLANORA_SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP is not configured.")
    port = int(env_value("PLANORA_SMTP_PORT", "587"))
    username = env_value("PLANORA_SMTP_USERNAME", "")
    password = env_value("PLANORA_SMTP_PASSWORD", "")
    sender = env_value("PLANORA_SMTP_FROM", username or "no-reply@planora.local")
    use_tls = env_bool("PLANORA_SMTP_STARTTLS", True)

    email = EmailMessage()
    email["From"] = sender
    email["To"] = message.to_email
    email["Subject"] = message.subject
    email.set_content(message.body)

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(email)


def email_auth_public_config() -> dict[str, Any]:
    return {
        "mode": "email_password",
        "registration_enabled": registration_enabled(),
        "email_verification_required": email_verification_required(),
        "smtp_configured": smtp_configured(),
    }


def expires_at(seconds: int) -> float:
    return time.time() + int(seconds)
