/**
 * AuditLogPage — browse audit events, manage sinks & retention (Sprint 14b D2).
 * Route: /audit
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface AuditEvent {
  id: string;
  actor: string;
  action: string;
  outcome: string;
  detail: Record<string, unknown> | null;
  session_key: string | null;
  created_at: string;
}

interface AuditStats {
  total: number;
  oldest: string | null;
  newest: string | null;
  by_outcome: Record<string, number>;
}

interface AuditSink {
  id: string;
  kind: string;
  name: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
}

export default function AuditLogPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [sinks, setSinks] = useState<AuditSink[]>([]);
  const [tab, setTab] = useState<'events' | 'sinks'>('events');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);
  const [actionFilter, setActionFilter] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (actionFilter) params.set('action', actionFilter);
      if (outcomeFilter) params.set('outcome', outcomeFilter);
      const [evts, st, sk] = await Promise.all([
        api.get<AuditEvent[]>(`/logs?${params}`),
        api.get<AuditStats>('/audit/stats'),
        api.get<AuditSink[]>('/audit/sinks'),
      ]);
      setEvents(evts);
      setStats(st);
      setSinks(sk);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit, actionFilter, outcomeFilter]);

  useEffect(() => { load(); }, [load]);

  const toggleSink = async (sink: AuditSink) => {
    try {
      await api.patch(`/audit/sinks/${sink.id}`, { enabled: !sink.enabled });
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const applyRetention = async () => {
    try {
      await api.post('/audit/retention/apply', {});
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const outcomeColor: Record<string, string> = {
    success: '#22c55e',
    failure: '#ef4444',
    error: '#f97316',
    denied: '#a855f7',
  };

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 8 }}>📋 Audit Log</h2>

      {stats && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
          <StatBadge label="Total events" value={String(stats.total)} />
          {Object.entries(stats.by_outcome).map(([k, v]) => (
            <StatBadge key={k} label={k} value={String(v)} color={outcomeColor[k]} />
          ))}
        </div>
      )}

      {error && (
        <div style={{ color: '#ef4444', marginBottom: 12, padding: 10, background: '#fef2f2', borderRadius: 6 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['events', 'sinks'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: tab === t ? 'var(--color-primary, #6366f1)' : 'var(--color-surface-alt)',
              color: tab === t ? '#fff' : 'var(--color-on-surface)',
              fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t === 'events' ? 'Events' : 'Sinks'}
          </button>
        ))}
        <button onClick={load} style={btnStyle}>↻ Refresh</button>
        <button onClick={applyRetention} style={{ ...btnStyle, marginLeft: 'auto' }}>Apply Retention</button>
      </div>

      {tab === 'events' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <input
              placeholder="Filter by action prefix…"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              style={inputStyle}
            />
            <select
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value)}
              style={inputStyle}
            >
              <option value="">All outcomes</option>
              {['success', 'failure', 'error', 'denied'].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={inputStyle}
            >
              {[25, 50, 100, 200].map((v) => <option key={v} value={v}>{v} rows</option>)}
            </select>
          </div>

          {loading && <div style={{ color: 'var(--color-on-muted)' }}>Loading…</div>}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                {['Time', 'Actor', 'Action', 'Outcome', 'Session'].map((h) => (
                  <th key={h} style={{ padding: '6px 10px', textAlign: 'left', color: 'var(--color-on-muted)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr
                  key={ev.id}
                  style={{ borderBottom: '1px solid var(--color-border)' }}
                >
                  <td style={{ padding: '5px 10px', whiteSpace: 'nowrap' }}>
                    {new Date(ev.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: '5px 10px' }}>{ev.actor}</td>
                  <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>{ev.action}</td>
                  <td style={{ padding: '5px 10px' }}>
                    <span style={{
                      padding: '1px 7px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                      background: `${outcomeColor[ev.outcome] ?? '#6b7280'}20`,
                      color: outcomeColor[ev.outcome] ?? '#6b7280',
                    }}>
                      {ev.outcome}
                    </span>
                  </td>
                  <td style={{ padding: '5px 10px', fontFamily: 'monospace', fontSize: 11 }}>
                    {ev.session_key ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length === 0 && !loading && (
            <div style={{ color: 'var(--color-on-muted)', fontStyle: 'italic', padding: 16 }}>No events.</div>
          )}
        </>
      )}

      {tab === 'sinks' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {sinks.map((sink) => (
            <div
              key={sink.id}
              style={{
                padding: '12px 16px', borderRadius: 8, background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                display: 'flex', alignItems: 'center', gap: 12,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{sink.name}</div>
                <div style={{ fontSize: 12, color: 'var(--color-on-muted)' }}>
                  kind={sink.kind} · config={JSON.stringify(sink.config)}
                </div>
              </div>
              <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="checkbox"
                  checked={sink.enabled}
                  onChange={() => toggleSink(sink)}
                />
                Enabled
              </label>
            </div>
          ))}
          {sinks.length === 0 && (
            <div style={{ color: 'var(--color-on-muted)', fontStyle: 'italic' }}>No sinks configured.</div>
          )}
        </div>
      )}
    </div>
  );
}

function StatBadge({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      padding: '6px 14px', borderRadius: 8,
      background: 'var(--color-surface)', border: '1px solid var(--color-border)',
      fontSize: 13,
    }}>
      <span style={{ color: 'var(--color-on-muted)', marginRight: 4 }}>{label}:</span>
      <strong style={{ color: color ?? 'var(--color-on-surface)' }}>{value}</strong>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
  background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)',
};

const inputStyle: React.CSSProperties = {
  padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)',
  background: 'var(--color-surface)', color: 'var(--color-on-surface)', fontSize: 13,
};
