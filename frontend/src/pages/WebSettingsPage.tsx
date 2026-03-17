/**
 * WebSettingsPage — configure web access policy and search providers (Sprint 13, D3).
 *
 * Accessible via /web-settings route.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface WebPolicy {
  default_provider: string;
  max_results: number;
  safe_search: string;          // e.g. "moderate" | "strict" | "off"
  timeout_s: number;
  brave_api_key: string;
  tavily_api_key: string;
  google_api_key: string;
  google_cx: string;
  bing_api_key: string;
  searxng_url: string;
  url_blocklist: string[];
  url_allowlist: string[];
  blocklist_mode: string;
  requests_per_minute: number;
}

interface ProviderInfo {
  name: string;
  needs_api_key: boolean;
  is_configured: boolean;
  is_default: boolean;
}

const DEFAULT_POLICY: WebPolicy = {
  default_provider: 'duckduckgo',
  max_results: 5,
  safe_search: 'moderate',
  timeout_s: 15,
  brave_api_key: '',
  tavily_api_key: '',
  google_api_key: '',
  google_cx: '',
  bing_api_key: '',
  searxng_url: '',
  url_blocklist: [],
  url_allowlist: [],
  blocklist_mode: 'blocklist',
  requests_per_minute: 0,
};

const card: React.CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: 20,
};

const btn = (color = '#4a9eff'): React.CSSProperties => ({
  padding: '7px 16px',
  borderRadius: 5,
  border: 'none',
  background: color,
  color: '#fff',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 600,
});

const inputStyle: React.CSSProperties = {
  padding: '7px 10px',
  borderRadius: 5,
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)',
  color: 'var(--color-text)',
  fontSize: 13,
  width: '100%',
  boxSizing: 'border-box',
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--color-text-muted)',
  marginBottom: 4,
};

const sectionTitle: React.CSSProperties = {
  margin: '0 0 12px',
  fontSize: 15,
  fontWeight: 700,
};

function MaskedInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? 'Enter API key…'}
        style={{ ...inputStyle, flex: 1 }}
        autoComplete="off"
      />
      <button
        type="button"
        onClick={() => setVisible(v => !v)}
        style={{
          padding: '6px 10px',
          borderRadius: 5,
          border: '1px solid var(--color-border)',
          background: 'var(--color-bg)',
          cursor: 'pointer',
          fontSize: 13,
          color: 'var(--color-text-muted)',
        }}
        title={visible ? 'Hide' : 'Show'}
      >
        {visible ? '🙈' : '👁'}
      </button>
    </div>
  );
}

export default function WebSettingsPage() {
  const [policy, setPolicy] = useState<WebPolicy>(DEFAULT_POLICY);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Text area buffers for array fields (newline-separated)
  const [blocklistText, setBlocklistText] = useState('');
  const [allowlistText, setAllowlistText] = useState('');

  const load = useCallback(async () => {
    try {
      const [policyData, providerData] = await Promise.all([
        api.get<WebPolicy>('/web-policy'),
        api.get<{ providers: ProviderInfo[] }>('/web-policy/providers'),
      ]);
      setPolicy(policyData);
      setProviders(providerData.providers);
      setBlocklistText((policyData.url_blocklist ?? []).join('\n'));
      setAllowlistText((policyData.url_allowlist ?? []).join('\n'));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const payload: WebPolicy = {
        ...policy,
        url_blocklist: blocklistText.split('\n').map(s => s.trim()).filter(Boolean),
        url_allowlist: allowlistText.split('\n').map(s => s.trim()).filter(Boolean),
      };
      await api.put('/web-policy', payload);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const set = <K extends keyof WebPolicy>(key: K, val: WebPolicy[K]) =>
    setPolicy(p => ({ ...p, [key]: val }));

  if (loading) return <p style={{ padding: 24, color: 'var(--color-text-muted)' }}>Loading…</p>;

  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header */}
      <div>
        <h1 style={{ margin: 0, fontSize: 22 }}>🌐 Web Settings</h1>
        <p style={{ margin: '4px 0 0', color: 'var(--color-text-muted)', fontSize: 13 }}>
          Configure search providers, access policy, and rate limits.
        </p>
      </div>

      {error && (
        <div style={{ padding: 12, borderRadius: 6, background: '#fee2e2', color: '#991b1b', fontSize: 13 }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: 12, cursor: 'pointer', background: 'none', border: 'none', color: '#991b1b', fontWeight: 700 }}>✕</button>
        </div>
      )}

      {success && (
        <div style={{ padding: 12, borderRadius: 6, background: '#dcfce7', color: '#166534', fontSize: 13 }}>
          ✓ Settings saved successfully.
        </div>
      )}

      {/* Search Providers */}
      <div style={card}>
        <h3 style={sectionTitle}>Search Providers</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {providers.map(p => (
            <label
              key={p.name}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 10,
                padding: '10px 12px',
                borderRadius: 6,
                border: `1px solid ${policy.default_provider === p.name ? '#4a9eff' : 'var(--color-border)'}`,
                cursor: 'pointer',
                background: policy.default_provider === p.name ? 'rgba(74,158,255,0.06)' : 'transparent',
              }}
            >
              <input
                type="radio"
                name="provider"
                value={p.name}
                checked={policy.default_provider === p.name}
                onChange={() => set('default_provider', p.name)}
                style={{ marginTop: 2, cursor: 'pointer' }}
              />
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <strong style={{ fontSize: 13 }}>{p.name}</strong>
                  {p.needs_api_key && !p.is_configured && (
                    <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: '#fee2e2', color: '#991b1b' }}>
                      Key required
                    </span>
                  )}
                  {p.is_configured && (
                    <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: '#dcfce7', color: '#166534' }}>
                      Ready
                    </span>
                  )}
                </div>
              </div>
            </label>
          ))}
          {providers.length === 0 && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>No providers available.</p>
          )}
        </div>
      </div>

      {/* API Keys */}
      <div style={card}>
        <h3 style={sectionTitle}>API Keys</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div>
            <span style={labelStyle}>Brave Search API Key</span>
            <MaskedInput value={policy.brave_api_key} onChange={v => set('brave_api_key', v)} placeholder="BSA-XXXX…" />
          </div>
          <div>
            <span style={labelStyle}>Tavily API Key</span>
            <MaskedInput value={policy.tavily_api_key} onChange={v => set('tavily_api_key', v)} placeholder="tvly-XXXX…" />
          </div>
          <div>
            <span style={labelStyle}>Google Custom Search API Key</span>
            <MaskedInput value={policy.google_api_key} onChange={v => set('google_api_key', v)} placeholder="AIza…" />
          </div>
          <div>
            <span style={labelStyle}>Google Custom Search Engine ID (CX)</span>
            <input
              style={inputStyle}
              value={policy.google_cx}
              onChange={e => set('google_cx', e.target.value)}
              placeholder="0123456789abcdef0"
            />
          </div>
          <div>
            <span style={labelStyle}>Bing Search API Key</span>
            <MaskedInput value={policy.bing_api_key} onChange={v => set('bing_api_key', v)} placeholder="Ocp-Apim-Subscription-Key…" />
          </div>
          <div>
            <span style={labelStyle}>SearXNG Base URL</span>
            <input
              style={inputStyle}
              value={policy.searxng_url}
              onChange={e => set('searxng_url', e.target.value)}
              placeholder="http://localhost:8080"
            />
          </div>
        </div>
      </div>

      {/* General Settings */}
      <div style={card}>
        <h3 style={sectionTitle}>Search Settings</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14 }}>
          <div>
            <span style={labelStyle}>Max Results Per Query</span>
            <input
              type="number"
              min={1}
              max={20}
              style={inputStyle}
              value={policy.max_results}
              onChange={e => set('max_results', parseInt(e.target.value) || 5)}
            />
          </div>
          <div>
            <span style={labelStyle}>Request Timeout (seconds)</span>
            <input
              type="number"
              min={5}
              max={60}
              style={inputStyle}
              value={policy.timeout_s}
              onChange={e => set('timeout_s', parseInt(e.target.value) || 15)}
            />
          </div>
          <div>
            <span style={labelStyle}>Rate Limit (req/min)</span>
            <input
              type="number"
              min={1}
              max={120}
              style={inputStyle}
              value={policy.requests_per_minute}
              onChange={e => set('requests_per_minute', parseInt(e.target.value) || 30)}
            />
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <span style={labelStyle}>Safe Search</span>
          <select
            style={{ ...inputStyle, width: 'auto', minWidth: 160 }}
            value={policy.safe_search}
            onChange={e => set('safe_search', e.target.value)}
          >
            <option value="off">Off</option>
            <option value="moderate">Moderate</option>
            <option value="strict">Strict</option>
          </select>
        </div>
      </div>

      {/* URL Access Policy */}
      <div style={card}>
        <h3 style={sectionTitle}>URL Access Policy</h3>
        <div style={{ marginBottom: 12 }}>
          <span style={labelStyle}>Mode</span>
          <div style={{ display: 'flex', gap: 16 }}>
            {(['blacklist', 'whitelist'] as const).map(mode => (
              <label key={mode} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="blocklist_mode"
                  value={mode}
                  checked={policy.blocklist_mode === mode}
                  onChange={() => set('blocklist_mode', mode)}
                />
                {mode === 'blacklist' ? '🚫 Blacklist (block listed URLs)' : '✅ Whitelist (allow only listed URLs)'}
              </label>
            ))}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div>
            <span style={labelStyle}>URL Blocklist (one per line)</span>
            <textarea
              style={{ ...inputStyle, minHeight: 100, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }}
              value={blocklistText}
              onChange={e => setBlocklistText(e.target.value)}
              placeholder={'example.com\n*.ads.com'}
            />
          </div>
          <div>
            <span style={labelStyle}>URL Allowlist (one per line)</span>
            <textarea
              style={{ ...inputStyle, minHeight: 100, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }}
              value={allowlistText}
              onChange={e => setAllowlistText(e.target.value)}
              placeholder={'trusted-source.com\nen.wikipedia.org'}
            />
          </div>
        </div>
      </div>

      {/* Save */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button style={btn()} onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : '💾 Save Settings'}
        </button>
      </div>
    </div>
  );
}
