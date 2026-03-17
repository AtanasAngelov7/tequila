/**
 * AuthSettingsPage — manage provider API keys (Sprint 12).
 *
 * Accessible via the /auth route.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface ProviderStatus {
  provider: string;
  configured: boolean;
  label: string;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama (local)',
};

const PROVIDER_HINTS: Record<string, string> = {
  openai: 'sk-…',
  anthropic: 'sk-ant-…',
  ollama: 'Leave blank for default local endpoint',
};

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
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [saveStatus, setSaveStatus] = useState<Record<string, SaveStatus>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      const data = await api.get<{ providers: ProviderStatus[] }>('/auth/providers');
      setProviders(data.providers);
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
      setSaveError((p) => ({ ...p, [providerId]: (err as { message?: string })?.message ?? 'Save failed' }));
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
      setSaveError((p) => ({ ...p, [providerId]: (err as { message?: string })?.message ?? 'Revoke failed' }));
    }
  };

  const toggleShow = (id: string) => setShowKey((p) => ({ ...p, [id]: !p[id] }));

  return (
    <div style={{ padding: '24px', maxWidth: 700, margin: '0 auto' }}>
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Auth Settings</h2>
        <p style={{ margin: '4px 0 0', color: 'var(--color-on-surface)', opacity: 0.6, fontSize: 13 }}>
          Store encrypted API keys for AI providers. Keys are never exposed after saving.
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
          {(providers.length > 0
            ? providers
            : Object.keys(PROVIDER_LABELS).map((id) => ({ provider: id, configured: false, label: PROVIDER_LABELS[id] }))
          ).map((p) => (
            <div key={p.provider} style={cardStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong style={{ fontSize: 15 }}>{p.label ?? PROVIDER_LABELS[p.provider] ?? p.provider}</strong>
                  <div style={{ marginTop: 3 }}>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: p.configured ? '#22c55e' : '#6b7280',
                        background: p.configured ? '#14532d22' : '#6b728022',
                        padding: '2px 8px',
                        borderRadius: 99,
                      }}
                    >
                      {p.configured ? '● Configured' : '○ Not configured'}
                    </span>
                  </div>
                </div>
                {p.configured && (
                  <button
                    style={btnStyle('#ef4444')}
                    onClick={() => handleRevoke(p.provider)}
                    disabled={saveStatus[p.provider] === 'saving'}
                  >
                    Revoke Key
                  </button>
                )}
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <input
                    type={showKey[p.provider] ? 'text' : 'password'}
                    placeholder={p.configured ? '••••••••  (replace existing key)' : (PROVIDER_HINTS[p.provider] ?? 'API key')}
                    value={keys[p.provider] ?? ''}
                    onChange={(e) => setKeys((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                    style={inputStyle}
                    onKeyDown={(e) => e.key === 'Enter' && handleSave(p.provider)}
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>
                <button
                  style={{ ...btnStyle('#374151'), padding: '7px 10px', minWidth: 36 }}
                  onClick={() => toggleShow(p.provider)}
                  title={showKey[p.provider] ? 'Hide' : 'Show'}
                >
                  {showKey[p.provider] ? '🙈' : '👁'}
                </button>
                <button
                  style={btnStyle(saveStatus[p.provider] === 'saved' ? '#22c55e' : '#4a9eff')}
                  onClick={() => handleSave(p.provider)}
                  disabled={!keys[p.provider]?.trim() || saveStatus[p.provider] === 'saving'}
                >
                  {saveStatus[p.provider] === 'saving'
                    ? 'Saving…'
                    : saveStatus[p.provider] === 'saved'
                    ? '✓ Saved'
                    : p.configured
                    ? 'Update'
                    : 'Save Key'}
                </button>
              </div>

              {saveError[p.provider] && (
                <div style={{ fontSize: 12, color: '#fca5a5', background: '#7f1d1d22', padding: '6px 10px', borderRadius: 4 }}>
                  {saveError[p.provider]}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 28, padding: '14px 16px', background: 'var(--color-surface)', borderRadius: 8, fontSize: 12, opacity: 0.55, lineHeight: 1.6 }}>
        🔒 Keys are encrypted with AES-128 (Fernet) before being written to the database.
        They cannot be retrieved in plain text via the API.
      </div>
    </div>
  );
}
