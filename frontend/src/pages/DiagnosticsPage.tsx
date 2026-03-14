/**
 * DiagnosticsPage — system status panel (§13.3 / §D2 Sprint 03).
 *
 * Displays the full SystemStatus response from GET /api/status,
 * including DB stats, active sessions, provider stubs, and scheduler.
 *
 * Accessible via the /diagnostics route.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface ProviderStatus {
  provider_id: string;
  available: boolean;
  circuit_state: string;
  model_count: number;
  last_error: string | null;
}

interface PluginStatus {
  plugin_id: string;
  status: string;
  healthy: boolean | null;
  last_error: string | null;
}

interface SystemStatus {
  status: string;
  app: string;
  version: string;
  uptime_s: number;
  started_at: string;
  providers: ProviderStatus[];
  plugins: PluginStatus[];
  db_ok: boolean;
  db_size_mb: number;
  db_wal_size_mb: number;
  active_session_count: number;
  active_turn_count: number;
  memory_extract_count: number;
  entity_count: number;
  embedding_index_status: string;
  scheduler_status: string;
  pending_jobs: number;
  config_keys: number;
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function DiagnosticsPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<SystemStatus>('/status');
      setStatus(data);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e?.message ?? 'Failed to load status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div style={{ padding: '24px 32px', maxWidth: 860, color: 'var(--color-on-surface)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>System Diagnostics</h1>
        <button
          onClick={load}
          disabled={loading}
          style={{
            padding: '5px 14px',
            fontSize: 12,
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            background: 'none',
            cursor: 'pointer',
            color: 'var(--color-on-surface)',
          }}
        >
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {error && (
        <div
          style={{
            padding: '10px 14px',
            background: '#dc262622',
            border: '1px solid #dc262655',
            borderRadius: 8,
            color: '#dc2626',
            marginBottom: 20,
          }}
        >
          {error}
        </div>
      )}

      {status && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* ── Overview ──────────────────────────────────────────── */}
          <Section title="Overview">
            <Row label="Status">
              <Badge
                color={status.status === 'ok' ? '#16a34a' : '#dc2626'}
                text={status.status.toUpperCase()}
              />
            </Row>
            <Row label="App">{status.app} v{status.version}</Row>
            <Row label="Uptime">{formatUptime(status.uptime_s)}</Row>
            <Row label="Started">
              {new Date(status.started_at).toLocaleString()}
            </Row>
          </Section>

          {/* ── Database ──────────────────────────────────────────── */}
          <Section title="Database">
            <Row label="Health">
              <Badge color={status.db_ok ? '#16a34a' : '#dc2626'} text={status.db_ok ? 'OK' : 'ERROR'} />
            </Row>
            <Row label="DB size">{status.db_size_mb.toFixed(2)} MB</Row>
            <Row label="WAL size">{status.db_wal_size_mb.toFixed(2)} MB</Row>
          </Section>

          {/* ── Sessions ──────────────────────────────────────────── */}
          <Section title="Sessions">
            <Row label="Active sessions">{status.active_session_count}</Row>
            <Row label="In-flight turns">{status.active_turn_count}</Row>
          </Section>

          {/* ── Providers ─────────────────────────────────────────── */}
          <Section title="Providers">
            {status.providers.length === 0 ? (
              <div style={{ opacity: 0.5, fontSize: 13 }}>
                No providers configured (setup wizard required).
              </div>
            ) : (
              status.providers.map((p) => (
                <Row key={p.provider_id} label={p.provider_id}>
                  <Badge color={p.available ? '#16a34a' : '#dc2626'} text={p.available ? 'Available' : 'Unavailable'} />
                  {' '}
                  {p.circuit_state} · {p.model_count} models
                  {p.last_error && (
                    <span style={{ color: '#dc2626', marginLeft: 6 }}>{p.last_error}</span>
                  )}
                </Row>
              ))
            )}
          </Section>

          {/* ── Memory ────────────────────────────────────────────── */}
          <Section title="Memory (stub — Sprint 05)">
            <Row label="Memory extracts">{status.memory_extract_count}</Row>
            <Row label="Entities">{status.entity_count}</Row>
            <Row label="Embedding index">{status.embedding_index_status}</Row>
          </Section>

          {/* ── Scheduler ─────────────────────────────────────────── */}
          <Section title="Scheduler (stub — Sprint 07)">
            <Row label="Status">{status.scheduler_status}</Row>
            <Row label="Pending jobs">{status.pending_jobs}</Row>
          </Section>

          {/* ── Config ────────────────────────────────────────────── */}
          <Section title="Configuration">
            <Row label="Loaded config keys">{status.config_keys}</Row>
          </Section>
        </div>
      )}
    </div>
  );
}

// ── Small sub-components ────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '10px 16px',
          fontWeight: 600,
          fontSize: 13,
          backgroundColor: 'var(--color-sidebar)',
          borderBottom: '1px solid var(--color-border)',
          letterSpacing: '0.03em',
          textTransform: 'uppercase',
        }}
      >
        {title}
      </div>
      <div style={{ padding: '6px 0' }}>{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '6px 16px',
        fontSize: 13,
        gap: 12,
      }}
    >
      <span style={{ width: 200, flexShrink: 0, opacity: 0.6 }}>{label}</span>
      <span>{children}</span>
    </div>
  );
}

function Badge({ color, text }: { color: string; text: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 8px',
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.04em',
        borderRadius: 4,
        backgroundColor: `${color}22`,
        color,
        border: `1px solid ${color}55`,
      }}
    >
      {text}
    </span>
  );
}
