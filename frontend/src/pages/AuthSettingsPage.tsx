/**
 * AuthSettingsPage — manage provider API keys and web sessions (Sprint 17).
 *
 * Supports:
 *  - API key providers: openai, anthropic, gemini, ollama
 *  - Web session providers: openai_web, anthropic_web, gemini_web
 *    (shown as a second tab on each corresponding card)
 *
 * Accessible via the /auth route.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import SessionCaptureFlow from '../components/SessionCaptureFlow';

interface ProviderStatus {
  provider: string;
  configured: boolean;
  label: string;
  credential_type?: string;
}

interface SessionStatus {
  connected: boolean;
  method: string | null;
  captured_at: string | null;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';
type AuthTab = 'api_key' | 'web_session';

// API-key providers shown as cards (in order)
const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Google Gemini',
  ollama: 'Ollama (local)',
};

const PROVIDER_HINTS: Record<string, string> = {
  openai: 'sk-…',
  anthropic: 'sk-ant-…',
  gemini: 'AIza…',
  ollama: 'Leave blank for default local endpoint',
};

// Map from api-key provider → its web session counterpart
const WEB_COUNTERPART: Record<string, string> = {
  openai: 'openai_web',
  anthropic: 'anthropic_web',
  gemini: 'gemini_web',
};

const API_KEY_PROVIDERS = Object.keys(PROVIDER_LABELS);

// ── Styles ───────────────────────────────────────────────────────────────────

const cardStyle: React.CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: '20px',
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 12px',
  borderRadius: 6,
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)',
  color: 'var(--color-on-surface)',
  fontSize: 13,
  fontFamily: 'monospace',
  boxSizing: 'border-box',
};

const badgeStyle = (active: boolean): React.CSSProperties => ({
  fontSize: 11,
  fontWeight: 600,
  color: active ? '#22c55e' : '#6b7280',
  background: active ? '#14532d22' : '#6b728022',
  padding: '2px 8px',
  borderRadius: 99,
});

const btnStyle = (color = '#4a9eff'): React.CSSProperties => ({
  padding: '7px 16px',
  borderRadius: 5,
  border: 'none',
  background: color,
  color: '#fff',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 600,
});

export default function AuthSettingsPage() {
  // API-key provider state (keyed by provider id e.g. "openai")
  const [providers, setProviders] = useState<Record<string, ProviderStatus>>({});
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [saveStatus, setSaveStatus] = useState<Record<string, SaveStatus>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});

  // Web session state (keyed by web provider id e.g. "openai_web")
  const [sessionStatus, setSessionStatus] = useState<Record<string, SessionStatus>>({});
  const [activeTab, setActiveTab] = useState<Record<string, AuthTab>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      const data = await api.get<{ providers: ProviderStatus[] }>('/auth/providers');
      const map: Record<string, ProviderStatus> = {};
      for (const p of data.providers) {
        map[p.provider] = p;
      }
      setProviders(map);

      // Load web session status for each web counterpart in parallel
      const webEntries = Object.entries(WEB_COUNTERPART);
      const statuses = await Promise.allSettled(
        webEntries.map(([, webId]) =>
          api.get<SessionStatus>(`/auth/session/${webId}/status`)
        )
      );
      const newSessionStatus: Record<string, SessionStatus> = {};
      webEntries.forEach(([, webId], i) => {
        const result = statuses[i];
        if (result.status === 'fulfilled') {
          newSessionStatus[webId] = result.value;
        } else {
          newSessionStatus[webId] = { connected: false, method: null, captured_at: null };
        }
      });
      setSessionStatus(newSessionStatus);
    } catch (err: unknown) {
      setPageError((err as { message?: string })?.message ?? 'Failed to load providers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async (providerId: string) => {
    const key = (keys[providerId] ?? '').trim();
    if (!key) return;
    setSaveStatus((p) => ({ ...p, [providerId]: 'saving' }));
    setSaveError((p) => ({ ...p, [providerId]: '' }));
    try {
      await api.post(`/auth/providers/${providerId}/key`, { key });
      setSaveStatus((p) => ({ ...p, [providerId]: 'saved' }));
      setKeys((p) => ({ ...p, [providerId]: '' }));
      await load();
      setTimeout(() => setSaveStatus((p) => ({ ...p, [providerId]: 'idle' })), 2000);
    } catch (err: unknown) {
      setSaveStatus((p) => ({ ...p, [providerId]: 'error' }));
      setSaveError((p) => ({
        ...p,
        [providerId]: (err as { message?: string })?.message ?? 'Save failed',
      }));
    }
  };

  const handleRevoke = async (providerId: string) => {
    if (!confirm(`Revoke API key for ${PROVIDER_LABELS[providerId] ?? providerId}?`)) return;
    setSaveStatus((p) => ({ ...p, [providerId]: 'saving' }));
    try {
      await api.delete(`/auth/providers/${providerId}/key`);
      setSaveStatus((p) => ({ ...p, [providerId]: 'idle' }));
      await load();
    } catch (err: unknown) {
      setSaveStatus((p) => ({ ...p, [providerId]: 'error' }));
      setSaveError((p) => ({
        ...p,
        [providerId]: (err as { message?: string })?.message ?? 'Revoke failed',
      }));
    }
  };

  const handleDisconnect = async (webId: string) => {
    const label = PROVIDER_LABELS[webId.replace('_web', '')] ?? webId;
    if (!confirm(`Disconnect web session for ${label}?`)) return;
    try {
      await api.delete(`/auth/session/${webId}`);
      await load();
    } catch (err: unknown) {
      console.error('Disconnect failed:', err);
    }
  };

  const toggleShow = (id: string) => setShowKey((p) => ({ ...p, [id]: !p[id] }));
  const getTab = (id: string): AuthTab => activeTab[id] ?? 'api_key';
  const setTab = (id: string, tab: AuthTab) => setActiveTab((p) => ({ ...p, [id]: tab }));

  return (
    <div style={{ padding: '24px', maxWidth: 700, margin: '0 auto' }}>
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Auth Settings</h2>
        <p style={{ margin: '4px 0 0', color: 'var(--color-on-surface)', opacity: 0.6, fontSize: 13 }}>
          Manage API keys and web sessions for AI providers. Keys are never exposed after saving.
        </p>
      </div>

      {pageError && (
        <div style={{ background: '#7f1d1d', color: '#fca5a5', padding: '10px 14px', borderRadius: 6, marginBottom: 16, fontSize: 13 }}>
          {pageError}
        </div>
      )}

      {loading ? (
        <p style={{ opacity: 0.5 }}>Loading…</p>
      ) : (
        <div style={{ display: 'grid', gap: 16 }}>
          {API_KEY_PROVIDERS.map((pid) => {
            const p = providers[pid] ?? { provider: pid, configured: false, label: PROVIDER_LABELS[pid] };
            const webId = WEB_COUNTERPART[pid];
            const hasWebOption = Boolean(webId);
            const tab = getTab(pid);
            const webConnected = webId ? (sessionStatus[webId]?.connected ?? false) : false;

            return (
            <div key={pid} style={cardStyle}>
              {/* Card header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <strong style={{ fontSize: 15 }}>{PROVIDER_LABELS[pid] ?? pid}</strong>
                  <div style={{ marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <span style={badgeStyle(p.configured)}>
                      {p.configured ? '● API Key' : '○ No API Key'}
                    </span>
                    {hasWebOption && (
                      <span style={badgeStyle(webConnected)}>
                        {webConnected ? '● Web Session' : '○ No Web Session'}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {p.configured && tab === 'api_key' && (
                    <button
                      style={btnStyle('#ef4444')}
                      onClick={() => handleRevoke(pid)}
                      disabled={saveStatus[pid] === 'saving'}
                    >
                      Revoke Key
                    </button>
                  )}
                  {hasWebOption && webConnected && tab === 'web_session' && (
                    <button style={btnStyle('#ef4444')} onClick={() => handleDisconnect(webId)}>
                      Disconnect
                    </button>
                  )}
                </div>
              </div>

              {/* Tab bar (only for providers with a web counterpart) */}
              {hasWebOption && (
                <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--color-border)' }}>
                  {(['api_key', 'web_session'] as AuthTab[]).map((t) => (
                    <button
                      key={t}
                      onClick={() => setTab(pid, t)}
                      style={{
                        padding: '6px 16px',
                        border: 'none',
                        borderBottom: tab === t ? '2px solid var(--color-primary)' : '2px solid transparent',
                        background: 'transparent',
                        color: tab === t ? 'var(--color-primary)' : 'var(--color-on-surface)',
                        cursor: 'pointer',
                        fontSize: 13,
                        fontWeight: tab === t ? 600 : 400,
                        marginBottom: -1,
                      }}
                    >
                      {t === 'api_key' ? 'API Key' : 'Web Session'}
                    </button>
                  ))}
                </div>
              )}

              {/* API Key tab */}
              {tab === 'api_key' && (
                <>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <div style={{ position: 'relative', flex: 1 }}>
                      <input
                        type={showKey[pid] ? 'text' : 'password'}
                        placeholder={p.configured ? '••••••••  (replace existing key)' : (PROVIDER_HINTS[pid] ?? 'API key')}
                        value={keys[pid] ?? ''}
                        onChange={(e) => setKeys((prev) => ({ ...prev, [pid]: e.target.value }))}
                        style={inputStyle}
                        onKeyDown={(e) => e.key === 'Enter' && handleSave(pid)}
                        autoComplete="off"
                        spellCheck={false}
                      />
                    </div>
                    <button
                      style={{ ...btnStyle('#374151'), padding: '7px 10px', minWidth: 36 }}
                      onClick={() => toggleShow(pid)}
                      title={showKey[pid] ? 'Hide' : 'Show'}
                    >
                      {showKey[pid] ? '🙈' : '👁'}
                    </button>
                    <button
                      style={btnStyle(saveStatus[pid] === 'saved' ? '#22c55e' : '#4a9eff')}
                      onClick={() => handleSave(pid)}
                      disabled={!keys[pid]?.trim() || saveStatus[pid] === 'saving'}
                    >
                      {saveStatus[pid] === 'saving'
                        ? 'Saving…'
                        : saveStatus[pid] === 'saved'
                        ? '✓ Saved'
                        : p.configured
                        ? 'Update'
                        : 'Save Key'}
                    </button>
                  </div>
                  {saveError[pid] && (
                    <div style={{ fontSize: 12, color: '#fca5a5', background: '#7f1d1d22', padding: '6px 10px', borderRadius: 4 }}>
                      {saveError[pid]}
                    </div>
                  )}
                </>
              )}

              {/* Web Session tab */}
              {tab === 'web_session' && hasWebOption && (
                <SessionCaptureFlow
                  provider={webId}
                  providerLabel={PROVIDER_LABELS[pid] ?? pid}
                  onSuccess={load}
                />
              )}
            </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: 28, padding: '14px 16px', background: 'var(--color-surface)', borderRadius: 8, fontSize: 12, opacity: 0.55, lineHeight: 1.6 }}>
        🔒 API keys are encrypted with AES-128 (Fernet) before being written to the database.
        They cannot be retrieved in plain text via the API.
      </div>
    </div>
  );
}
