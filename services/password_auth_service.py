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
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from services.env_service import env_bool, env_bool_strict, env_value


_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class InlineImage:
    content_id: str
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class OutboundEmail:
    to_email: str
    subject: str
    body: str
    html_body: str = ""
    inline_images: tuple[InlineImage, ...] = ()


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
    pepper = env_value("PLANORA_TOKEN_PEPPER", "")
    auth_secret = env_value("PLANORA_AUTH_SECRET", "")
    if env_bool_strict("PLANORA_PRODUCTION", False):
        if not pepper:
            raise RuntimeError(
                "PLANORA_TOKEN_PEPPER or PLANORA_TOKEN_PEPPER_FILE is required in production."
            )
        if len(pepper.encode("utf-8")) < 32:
            raise RuntimeError(
                "PLANORA_TOKEN_PEPPER must contain at least 32 UTF-8 bytes in production."
            )
        if auth_secret and hmac.compare_digest(
            pepper.encode("utf-8"), auth_secret.encode("utf-8")
        ):
            raise RuntimeError(
                "PLANORA_TOKEN_PEPPER must be independent from PLANORA_AUTH_SECRET in production."
            )
    return pepper or auth_secret or "planora-local-token-pepper"


def hash_token(token: str) -> str:
    digest = hmac.new(secret_pepper().encode("utf-8"), str(token).encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def email_verification_required() -> bool:
    return env_bool("PLANORA_EMAIL_VERIFICATION_REQUIRED", True)


def registration_enabled() -> bool:
    return env_bool("PLANORA_REGISTRATION_ENABLED", True)


def smtp_configured() -> bool:
    return bool(env_value("PLANORA_SMTP_HOST", ""))


def _validated_public_base_url(value: str, *, require_https: bool) -> str:
    base_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("PLANORA_PUBLIC_BASE_URL has an invalid port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        raise RuntimeError("PLANORA_PUBLIC_BASE_URL must be an absolute http(s) URL without credentials, query, or fragment.")
    if require_https and parsed.scheme != "https":
        raise RuntimeError("PLANORA_PUBLIC_BASE_URL must use https in production.")
    return base_url


def verification_base_url(default_base_url: str) -> str:
    production = env_bool_strict("PLANORA_PRODUCTION", False)
    configured = env_value("PLANORA_PUBLIC_BASE_URL", "").strip()
    if not configured:
        domain = env_value("PLANORA_DOMAIN", "").strip().rstrip("/")
        if domain:
            parsed_domain = urlparse(f"//{domain}")
            if (
                not parsed_domain.hostname
                or parsed_domain.username is not None
                or parsed_domain.password is not None
                or parsed_domain.path
                or parsed_domain.query
                or parsed_domain.fragment
            ):
                raise RuntimeError("PLANORA_DOMAIN must contain only a hostname and optional port.")
            configured = f"https://{domain}"
    if configured:
        return _validated_public_base_url(configured, require_https=production)
    if production:
        raise RuntimeError(
            "PLANORA_PUBLIC_BASE_URL or PLANORA_DOMAIN is required in production."
        )
    return str(default_base_url or "").rstrip("/")


def _planora_email_images() -> tuple[InlineImage, ...]:
    candidates = (
        Path(__file__).resolve().parent / "assets" / "planora_elephant.png",
        Path(__file__).resolve().parents[1] / "web" / "public" / "app-icon.png",
    )
    for candidate in candidates:
        if candidate.is_file():
            return (
                InlineImage(
                    content_id="planora-elephant",
                    filename="planora-elephant.png",
                    content_type="image/png",
                    content=candidate.read_bytes(),
                ),
            )
    raise RuntimeError("The Planora email logo asset is missing.")


def _email_shell(*, title: str, preview: str, body_html: str) -> str:
    return f"""\
<!doctype html>
<html lang="en">
  <body style="margin:0;background:#eef3f7;font-family:Inter,Segoe UI,Arial,sans-serif;color:#17212b;">
    <div style="display:none;max-height:0;overflow:hidden;">{html.escape(preview)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef3f7;padding:36px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #d8e0e8;border-radius:20px;overflow:hidden;box-shadow:0 18px 48px rgba(33,50,70,.10);">
            <tr>
              <td style="height:7px;background:#256da8;font-size:0;line-height:0;">&nbsp;</td>
            </tr>
            <tr>
              <td style="padding:28px 32px 18px;">
                <table role="presentation" cellspacing="0" cellpadding="0"><tr>
                  <td style="padding-right:12px;"><img src="cid:planora-elephant" alt="Planora elephant" width="58" height="58" style="display:block;border:0;"></td>
                  <td><strong style="display:block;font-size:21px;line-height:1.1;color:#17212b;">Planora</strong><span style="font-size:13px;color:#566577;">Academic scheduling</span></td>
                </tr></table>
                <h1 style="margin:26px 0 0;font-size:28px;line-height:1.22;color:#17212b;">{html.escape(title)}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 32px;font-size:15px;line-height:1.65;color:#405063;">
                {body_html}
                <p style="margin:28px 0 0;padding-top:18px;border-top:1px solid #d8e0e8;color:#708096;font-size:13px;">If you did not request this, you can safely ignore this email.</p>
              </td>
            </tr>
          </table>
          <p style="margin:18px 0 0;color:#738294;font-size:12px;">Planora Academic Scheduler</p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def build_verification_email(base_url: str, to_email: str, token: str, code: str) -> OutboundEmail:
    url = f"{base_url}/auth/verify?token={token}"
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
            body_html=(
                "<p style=\"margin:0 0 18px;\">Welcome to Planora. Confirm your email to activate your account and access your organization schedules.</p>"
                f"<p style=\"margin:0 0 22px;\"><a href=\"{html.escape(url)}\" style=\"display:inline-block;background:#1f669b;color:#ffffff;text-decoration:none;font-weight:700;padding:13px 20px;border-radius:12px;\">Confirm account</a></p>"
                "<p style=\"margin:0 0 8px;\">You can also enter this confirmation code:</p>"
                f"<div style=\"display:inline-block;letter-spacing:6px;font-size:30px;font-weight:800;color:#0f4d78;background:#e2edf8;border:1px solid #b8cde0;border-radius:12px;padding:12px 18px;\">{html.escape(code)}</div>"
            ),
        ),
        inline_images=_planora_email_images(),
    )


def build_password_reset_email(base_url: str, to_email: str, token: str, code: str) -> OutboundEmail:
    url = f"{base_url}/login?reset_token={token}"
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
            body_html=(
                "<p style=\"margin:0 0 18px;\">We received a request to reset your Planora password. Use the secure link below or enter the code in Planora.</p>"
                f"<p style=\"margin:0 0 22px;\"><a href=\"{html.escape(url)}\" style=\"display:inline-block;background:#1f669b;color:#ffffff;text-decoration:none;font-weight:700;padding:13px 20px;border-radius:12px;\">Reset password</a></p>"
                "<p style=\"margin:0 0 8px;\">Reset code:</p>"
                f"<div style=\"display:inline-block;letter-spacing:6px;font-size:30px;font-weight:800;color:#0f4d78;background:#e2edf8;border:1px solid #b8cde0;border-radius:12px;padding:12px 18px;\">{html.escape(code)}</div>"
            ),
        ),
        inline_images=_planora_email_images(),
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
        html_part = email.get_payload()[-1]
        for image in message.inline_images:
            maintype, subtype = image.content_type.split("/", 1)
            html_part.add_related(
                image.content,
                maintype=maintype,
                subtype=subtype,
                cid=f"<{image.content_id}>",
                filename=image.filename,
                disposition="inline",
            )

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
