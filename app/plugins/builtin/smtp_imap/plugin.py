"""SMTP / IMAP email connector plugin (Sprint 12, §8.6).

Uses only Python standard-library ``imaplib``, ``smtplib``, and
``email`` — no pip dependencies required.

Required credentials (stored via ``/api/plugins/smtp_imap/credentials``):
- ``smtp_host``, ``smtp_port``, ``smtp_username``, ``smtp_password``
- ``imap_host``, ``imap_port``, ``imap_username``, ``imap_password``
"""
from __future__ import annotations

import asyncio
import email as emaillib
import imaplib
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.smtp_imap.tools import SMTP_IMAP_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)


class SmtpImapPlugin(PluginBase):
    """Generic SMTP/IMAP email connector."""

    plugin_id = "smtp_imap"
    name = "Email (SMTP/IMAP)"
    description = "Send and receive email via SMTP and IMAP using any mail server."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._smtp_config: dict[str, Any] = {}
        self._imap_config: dict[str, Any] = {}
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        pid = self.plugin_id
        smtp_host = config.get("smtp_host") or await auth_store(pid, "smtp_host")
        imap_host = config.get("imap_host") or await auth_store(pid, "imap_host")

        if not smtp_host:
            raise ValueError("smtp_host is required. Provide it via config or credentials.")

        self._smtp_config = {
            "host": smtp_host,
            "port": int(config.get("smtp_port") or await auth_store(pid, "smtp_port") or 587),
            "username": config.get("smtp_username") or await auth_store(pid, "smtp_username") or "",
            "password": await auth_store(pid, "smtp_password") or "",
            "use_tls": bool(config.get("smtp_use_tls", True)),
        }
        self._imap_config = {
            "host": imap_host or smtp_host,
            "port": int(config.get("imap_port") or await auth_store(pid, "imap_port") or 993),
            "username": config.get("imap_username") or await auth_store(pid, "imap_username") or self._smtp_config["username"],
            "password": await auth_store(pid, "imap_password") or self._smtp_config["password"],
            "use_ssl": bool(config.get("imap_use_ssl", True)),
        }

    async def activate(self) -> None:
        self._active = True

    async def deactivate(self) -> None:
        self._active = False

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return SMTP_IMAP_TOOLS

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="email",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=True,
        )

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="api_key", key_label="SMTP Password")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "smtp_host":     {"type": "string", "description": "SMTP server hostname"},
                "smtp_port":     {"type": "integer", "default": 587},
                "smtp_username": {"type": "string"},
                "smtp_use_tls":  {"type": "boolean", "default": True},
                "imap_host":     {"type": "string", "description": "IMAP server hostname"},
                "imap_port":     {"type": "integer", "default": 993},
                "imap_username": {"type": "string"},
                "imap_use_ssl":  {"type": "boolean", "default": True},
            },
            "required": ["smtp_host"],
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies()  # stdlib only

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._smtp_config.get("host"):
            return PluginHealthResult(healthy=False, message="Not configured.")
        try:
            await asyncio.to_thread(self._smtp_noop)
            return PluginHealthResult(healthy=True, message="SMTP connection OK.")
        except Exception as exc:
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._smtp_config.get("host"):
            return PluginTestResult(success=False, message="Not configured.")
        import time

        start = time.monotonic()
        try:
            await asyncio.to_thread(self._smtp_noop)
            latency = int((time.monotonic() - start) * 1000)
            return PluginTestResult(success=True, message="SMTP NOOP OK.", latency_ms=latency)
        except Exception as exc:
            return PluginTestResult(success=False, message=str(exc))

    # ── Sync helpers (run via asyncio.to_thread) ──────────────────────────────

    def _smtp_noop(self) -> None:
        cfg = self._smtp_config
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            smtp.ehlo()
            if cfg["use_tls"]:
                smtp.starttls()
            if cfg["username"]:
                smtp.login(cfg["username"], cfg["password"])
            smtp.noop()

    def send_email_sync(
        self,
        to: str,
        subject: str,
        body: str,
        from_addr: str | None = None,
        html: bool = False,
    ) -> None:
        cfg = self._smtp_config
        sender = from_addr or cfg.get("username") or "noreply@localhost"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to
        msg.attach(MIMEText(body, "html" if html else "plain"))

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
            smtp.ehlo()
            if cfg["use_tls"]:
                smtp.starttls()
            if cfg["username"]:
                smtp.login(cfg["username"], cfg["password"])
            smtp.sendmail(sender, [to], msg.as_string())

    def list_messages_sync(
        self,
        folder: str = "INBOX",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        cfg = self._imap_config
        if cfg.get("use_ssl"):
            imap = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        else:
            imap = imaplib.IMAP4(cfg["host"], cfg["port"])
        imap.login(cfg["username"], cfg["password"])
        imap.select(folder)
        _, data = imap.search(None, "ALL")
        uids = data[0].split()[-limit:]
        messages = []
        for uid in reversed(uids):
            _, raw = imap.fetch(uid, "(RFC822)")
            for part in raw:
                if isinstance(part, tuple):
                    msg = emaillib.message_from_bytes(part[1])
                    messages.append({
                        "uid": uid.decode(),
                        "subject": msg.get("Subject", ""),
                        "from": msg.get("From", ""),
                        "date": msg.get("Date", ""),
                        "snippet": self._get_text(msg)[:200],
                    })
        imap.logout()
        return messages

    def _get_text(self, msg: Any) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode(errors="replace")
        return msg.get_payload(decode=True).decode(errors="replace") if isinstance(msg.get_payload(), bytes) else ""
