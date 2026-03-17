/**
 * PluginsPage — browse, install, configure and manage built-in plugins (Sprint 12).
 *
 * Accessible via the /plugins route.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface PluginRecord {
  plugin_id: string;
  name: string;
  description: string;
  version: string;
  plugin_type: string;
  connector_type: string | null;
  status: 'installed' | 'configured' | 'active' | 'error' | 'disabled';
  error_message: string | null;
}

interface PluginTestResult {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

const STATUS_COLORS: Record<PluginRecord['status'], string> = {
  installed: '#888',
  configured: '#4a9eff',
  active: '#22c55e',
  error: '#ef4444',
  disabled: '#6b7280',
};

const cardStyle: React.CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: '16px',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
};

const btnStyle = (color = '#4a9eff'): React.CSSProperties => ({
  padding: '5px 12px',
  borderRadius: 5,
  border: 'none',
  background: color,
  color: '#fff',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
});

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, PluginTestResult>>({});
  const [busyPlugins, setBusyPlugins] = useState<Set<string>>(new Set());

  const BUILTIN_IDS = ['webhooks', 'telegram', 'smtp_imap', 'gmail', 'google_calendar'];

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<PluginRecord[]>('/plugins');
      setPlugins(data);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Failed to load plugins');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setBusy = (id: string, busy: boolean) => {
    setBusyPlugins((prev) => {
      const next = new Set(prev);
      busy ? next.add(id) : next.delete(id);
      return next;
    });
  };

  const handleInstall = async (pluginId: string) => {
    setBusy(pluginId, true);
    try {
      await api.post('/plugins', { plugin_id: pluginId });
      await load();
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Install failed');
    } finally {
      setBusy(pluginId, false);
    }
  };

  const handleActivate = async (pluginId: string) => {
    setBusy(pluginId, true);
    try {
      await api.post(`/plugins/${pluginId}/activate`, {});
      await load();
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Activate failed');
    } finally {
      setBusy(pluginId, false);
    }
  };

  const handleDeactivate = async (pluginId: string) => {
    setBusy(pluginId, true);
    try {
      await api.post(`/plugins/${pluginId}/deactivate`, {});
      await load();
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Deactivate failed');
    } finally {
      setBusy(pluginId, false);
    }
  };

  const handleUninstall = async (pluginId: string) => {
    if (!confirm(`Uninstall plugin "${pluginId}"? This will delete its configuration.`)) return;
    setBusy(pluginId, true);
    try {
      await api.delete(`/plugins/${pluginId}`);
      await load();
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Uninstall failed');
    } finally {
      setBusy(pluginId, false);
    }
  };

  const handleTest = async (pluginId: string) => {
    setBusy(pluginId, true);
    try {
      const result = await api.post<PluginTestResult>(`/plugins/${pluginId}/test`, {});
      setTestResults((prev) => ({ ...prev, [pluginId]: result }));
    } catch (err: unknown) {
      setTestResults((prev) => ({
        ...prev,
        [pluginId]: { success: false, message: (err as { message?: string })?.message ?? 'Test failed', latency_ms: null },
      }));
    } finally {
      setBusy(pluginId, false);
    }
  };

  const installedIds = new Set(plugins.map((p) => p.plugin_id));

  return (
    <div style={{ padding: '24px', maxWidth: 900, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Plugins</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--color-on-surface)', opacity: 0.6, fontSize: 13 }}>
            Manage built-in connectors and integrations
          </p>
        </div>
        <button style={btnStyle('#374151')} onClick={load} disabled={loading}>
          {loading ? 'Loading…' : '↺ Refresh'}
        </button>
      </div>

      {error && (
        <div style={{ background: '#7f1d1d', color: '#fca5a5', padding: '10px 14px', borderRadius: 6, marginBottom: 16, fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* Installed plugins */}
      {plugins.length > 0 && (
        <section style={{ marginBottom: 32 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 600, textTransform: 'uppercase', opacity: 0.5, letterSpacing: '0.05em' }}>
            Installed ({plugins.length})
          </h3>
          <div style={{ display: 'grid', gap: 12 }}>
            {plugins.map((plugin) => (
              <div key={plugin.plugin_id} style={cardStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <strong style={{ fontSize: 15 }}>{plugin.name}</strong>
                      <span style={{ fontSize: 11, color: '#888' }}>v{plugin.version}</span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          color: STATUS_COLORS[plugin.status],
                          background: `${STATUS_COLORS[plugin.status]}22`,
                          padding: '2px 8px',
                          borderRadius: 99,
                        }}
                      >
                        {plugin.status}
                      </span>
                    </div>
                    <p style={{ margin: '4px 0 0', fontSize: 12, opacity: 0.6 }}>{plugin.description}</p>
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0, marginLeft: 12 }}>
                    {plugin.status !== 'active' && (
                      <button
                        style={btnStyle('#22c55e')}
                        onClick={() => handleActivate(plugin.plugin_id)}
                        disabled={busyPlugins.has(plugin.plugin_id)}
                      >
                        Activate
                      </button>
                    )}
                    {plugin.status === 'active' && (
                      <button
                        style={btnStyle('#6b7280')}
                        onClick={() => handleDeactivate(plugin.plugin_id)}
                        disabled={busyPlugins.has(plugin.plugin_id)}
                      >
                        Deactivate
                      </button>
                    )}
                    <button
                      style={btnStyle('#4a9eff')}
                      onClick={() => handleTest(plugin.plugin_id)}
                      disabled={busyPlugins.has(plugin.plugin_id)}
                    >
                      Test
                    </button>
                    <button
                      style={btnStyle('#ef4444')}
                      onClick={() => handleUninstall(plugin.plugin_id)}
                      disabled={busyPlugins.has(plugin.plugin_id)}
                    >
                      Remove
                    </button>
                  </div>
                </div>

                {plugin.error_message && (
                  <div style={{ fontSize: 12, color: '#fca5a5', background: '#7f1d1d22', padding: '6px 10px', borderRadius: 4 }}>
                    ⚠ {plugin.error_message}
                  </div>
                )}

                {testResults[plugin.plugin_id] && (
                  <div
                    style={{
                      fontSize: 12,
                      padding: '6px 10px',
                      borderRadius: 4,
                      background: testResults[plugin.plugin_id].success ? '#14532d22' : '#7f1d1d22',
                      color: testResults[plugin.plugin_id].success ? '#86efac' : '#fca5a5',
                    }}
                  >
                    {testResults[plugin.plugin_id].success ? '✓' : '✗'}{' '}
                    {testResults[plugin.plugin_id].message}
                    {testResults[plugin.plugin_id].latency_ms != null && (
                      <span style={{ opacity: 0.7, marginLeft: 8 }}>{testResults[plugin.plugin_id].latency_ms}ms</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Available to install */}
      {BUILTIN_IDS.filter((id) => !installedIds.has(id)).length > 0 && (
        <section>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 600, textTransform: 'uppercase', opacity: 0.5, letterSpacing: '0.05em' }}>
            Available Built-ins
          </h3>
          <div style={{ display: 'grid', gap: 8 }}>
            {BUILTIN_IDS.filter((id) => !installedIds.has(id)).map((id) => (
              <div key={id} style={{ ...cardStyle, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <strong style={{ fontSize: 14 }}>{id}</strong>
                  <p style={{ margin: '2px 0 0', fontSize: 12, opacity: 0.5 }}>Built-in plugin</p>
                </div>
                <button
                  style={btnStyle()}
                  onClick={() => handleInstall(id)}
                  disabled={busyPlugins.has(id)}
                >
                  {busyPlugins.has(id) ? 'Installing…' : 'Install'}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {!loading && plugins.length === 0 && BUILTIN_IDS.length === 0 && (
        <p style={{ opacity: 0.5, textAlign: 'center', marginTop: 48 }}>No plugins available.</p>
      )}
    </div>
  );
}
