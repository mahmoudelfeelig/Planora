from __future__ import annotations

import hashlib
import html
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
    html_body: str = ""


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


def new_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


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


def _email_shell(*, title: str, preview: str, logo_url: str, body_html: str) -> str:
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#f5f7fb;font-family:Inter,Segoe UI,Arial,sans-serif;color:#142033;">
    <div style="display:none;max-height:0;overflow:hidden;">{html.escape(preview)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f7fb;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #dbe4ef;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 18px;">
                <img src="{html.escape(logo_url)}" alt="Planora" width="56" height="56" style="display:block;border-radius:12px;margin-bottom:18px;">
                <h1 style="margin:0;font-size:26px;line-height:1.2;color:#111827;">{html.escape(title)}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 32px;font-size:15px;line-height:1.65;color:#40516a;">
                {body_html}
                <p style="margin:28px 0 0;color:#708096;font-size:13px;">If you did not request this, you can safely ignore this email.</p>
              </td>
            </tr>
          </table>
          <p style="margin:18px 0 0;color:#8a97aa;font-size:12px;">Planora Academic Scheduler</p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def build_verification_email(base_url: str, to_email: str, token: str, code: str) -> OutboundEmail:
    url = f"{base_url}/auth/verify?token={token}"
    logo_url = f"{base_url.rstrip('/')}/app-icon.png"
    return OutboundEmail(
        to_email=to_email,
        subject="Confirm your Planora account",
        body=(
            "Welcome to Planora.\n\n"
            "Confirm your account by opening this secure link:\n"
            f"{url}\n\n"
            "Or enter this confirmation code in Planora:\n"
            f"{code}\n\n"
            "If you did not register for Planora, ignore this email."
        ),
        html_body=_email_shell(
            title="Confirm your Planora account",
            preview="Use the secure link or confirmation code to activate your Planora account.",
            logo_url=logo_url,
            body_html=(
                "<p style=\"margin:0 0 18px;\">Welcome to Planora. Confirm your email to activate your account and access your organization schedules.</p>"
                f"<p style=\"margin:0 0 22px;\"><a href=\"{html.escape(url)}\" style=\"display:inline-block;background:#8d3bd1;color:#ffffff;text-decoration:none;font-weight:700;padding:12px 18px;border-radius:10px;\">Confirm account</a></p>"
                "<p style=\"margin:0 0 8px;\">You can also enter this confirmation code:</p>"
                f"<div style=\"display:inline-block;letter-spacing:6px;font-size:30px;font-weight:800;color:#111827;background:#f0edf8;border:1px solid #d7c8f0;border-radius:12px;padding:12px 18px;\">{html.escape(code)}</div>"
            ),
        ),
    )


def build_password_reset_email(base_url: str, to_email: str, token: str, code: str) -> OutboundEmail:
    url = f"{base_url}/login?reset_token={token}"
    logo_url = f"{base_url.rstrip('/')}/app-icon.png"
    return OutboundEmail(
        to_email=to_email,
        subject="Reset your Planora password",
        body=(
            "We received a request to reset your Planora password.\n\n"
            "Open this secure link to choose a new password:\n"
            f"{url}\n\n"
            "Or enter this reset code in Planora:\n"
            f"{code}\n\n"
            "If you did not request this, ignore this email."
        ),
        html_body=_email_shell(
            title="Reset your Planora password",
            preview="Use the secure link or reset code to choose a new Planora password.",
            logo_url=logo_url,
            body_html=(
                "<p style=\"margin:0 0 18px;\">We received a request to reset your Planora password. Use the secure link below or enter the code in Planora.</p>"
                f"<p style=\"margin:0 0 22px;\"><a href=\"{html.escape(url)}\" style=\"display:inline-block;background:#8d3bd1;color:#ffffff;text-decoration:none;font-weight:700;padding:12px 18px;border-radius:10px;\">Reset password</a></p>"
                "<p style=\"margin:0 0 8px;\">Reset code:</p>"
                f"<div style=\"display:inline-block;letter-spacing:6px;font-size:30px;font-weight:800;color:#111827;background:#f0edf8;border:1px solid #d7c8f0;border-radius:12px;padding:12px 18px;\">{html.escape(code)}</div>"
            ),
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
    if message.html_body:
        email.add_alternative(message.html_body, subtype="html")

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
