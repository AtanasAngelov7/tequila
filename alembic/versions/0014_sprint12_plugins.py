"""Sprint 12 — Plugin system, auth credentials, webhooks, dedup keys.

Tables added:
  plugins             — plugin registry (lifecycle state, config, status)
  plugin_credentials  — encrypted API keys and OAuth tokens per plugin
  webhook_endpoints   — inbound webhook channel config
  dedup_keys          — idempotency dedup store (§20.4)

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS plugins (
            plugin_id     TEXT NOT NULL PRIMARY KEY,
            name          TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            version       TEXT NOT NULL DEFAULT '1.0.0',
            plugin_type   TEXT NOT NULL
                CHECK (plugin_type IN ('connector', 'pipeline_hook', 'audit_sink')),
            connector_type TEXT
                CHECK (connector_type IS NULL OR connector_type IN ('builtin', 'mcp', 'custom')),
            config        TEXT NOT NULL DEFAULT '{}',
            status        TEXT NOT NULL DEFAULT 'installed'
                CHECK (status IN ('installed', 'configured', 'active', 'error', 'disabled')),
            error_message TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS plugin_credentials (
            plugin_id        TEXT NOT NULL,
            credential_key   TEXT NOT NULL,
            encrypted_value  TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            PRIMARY KEY (plugin_id, credential_key)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
            id           TEXT NOT NULL PRIMARY KEY,
            name         TEXT NOT NULL,
            plugin_id    TEXT NOT NULL DEFAULT 'webhooks',
            session_key  TEXT NOT NULL,
            secret_hash  TEXT,
            payload_path TEXT,
            active       INTEGER NOT NULL DEFAULT 1
                CHECK (active IN (0, 1)),
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS dedup_keys (
            source      TEXT NOT NULL,
            dedup_key   TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (source, dedup_key)
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_plugins_status ON plugins (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_plugins_type ON plugins (plugin_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_endpoints_plugin ON webhook_endpoints (plugin_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dedup_keys_source ON dedup_keys (source, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_plugin_credentials_plugin ON plugin_credentials (plugin_id)")

    # ── auth.* config keys ────────────────────────────────────────────────────
    # The encryption key is generated at startup and stored here.
    # An empty-string default signals "not yet generated".
    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO config
                (key, value, value_type, category, description, default_val, requires_restart)
            VALUES
                (:key, :value, :value_type, :category, :description, :default_val, :requires_restart)
            """
        ).bindparams(
            key="auth.encryption_key",
            value='""',
            value_type="str",
            category="auth",
            description="Fernet base64 symmetric key used to encrypt stored credentials. Generated at first start.",
            default_val='""',
            requires_restart=0,
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_plugin_credentials_plugin")
    op.execute("DROP INDEX IF EXISTS ix_dedup_keys_source")
    op.execute("DROP INDEX IF EXISTS ix_webhook_endpoints_plugin")
    op.execute("DROP INDEX IF EXISTS ix_plugins_type")
    op.execute("DROP INDEX IF EXISTS ix_plugins_status")
    op.execute("DROP TABLE IF EXISTS dedup_keys")
    op.execute("DROP TABLE IF EXISTS webhook_endpoints")
    op.execute("DROP TABLE IF EXISTS plugin_credentials")
    op.execute("DROP TABLE IF EXISTS plugins")
