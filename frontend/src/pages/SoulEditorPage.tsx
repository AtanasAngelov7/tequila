/**
 * SoulEditorPage — LLM-assisted soul generation + manual editing + version history.
 * Sprint 14a §4.1a
 *
 * Route: /soul-editor
 */
import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';

interface AgentSummary {
  agent_id: string;
  name: string;
}

interface SoulData {
  persona?: string;
  core_values?: string[];
  tone?: string;
  rules?: string[];
  communication_style?: string;
  [key: string]: unknown;
}

interface SoulVersion {
  version_id: string;
  agent_id: string;
  version_num: number;
  soul_json?: SoulData;
  change_note: string;
  created_at: string;
}

const cardStyle: React.CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: '16px',
};

const btnStyle = (color = '#4a9eff', small = false): React.CSSProperties => ({
  padding: small ? '4px 10px' : '7px 16px',
  borderRadius: 5, border: 'none', background: color,
  color: '#fff', cursor: 'pointer', fontSize: small ? 11 : 13, fontWeight: 600,
});

const inputStyle: React.CSSProperties = {
  background: 'var(--color-bg)',
  border: '1px solid var(--color-border)',
  borderRadius: 5,
  color: 'var(--color-on-surface)',
  padding: '6px 10px',
  fontSize: 13,
  width: '100%',
  boxSizing: 'border-box',
};

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  resize: 'vertical',
  fontFamily: 'monospace',
};

const labelStyle: React.CSSProperties = {
  fontSize: 12, fontWeight: 600,
  color: 'var(--color-on-surface)', opacity: 0.7, display: 'block', marginBottom: 4,
};

export default function SoulEditorPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>('');
  const [description, setDescription] = useState('');
  const [generating, setGenerating] = useState(false);
  const [soul, setSoul] = useState<SoulData>({});
  const [preview, setPreview] = useState<string>('');
  const [previewing, setPreviewing] = useState(false);
  const [history, setHistory] = useState<SoulVersion[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveAfterGenerate, setSaveAfterGenerate] = useState(true);
  const [rawJson, setRawJson] = useState('');
  const [editMode, setEditMode] = useState<'fields' | 'json'>('fields');

  /* ---------- load agents ---------- */
  useEffect(() => {
    api.get<AgentSummary[]>('/agents')
      .then(data => setAgents(data))
      .catch(() => setAgents([]));
  }, []);

  /* ---------- load history when agent changes ---------- */
  const loadHistory = useCallback(async (agentId: string) => {
    if (!agentId) return;
    setHistoryLoading(true);
    try {
      const data = await api.get<SoulVersion[]>(`/agents/${agentId}/soul/history`);
      setHistory(data);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedAgent) loadHistory(selectedAgent);
  }, [selectedAgent, loadHistory]);

  /* ---------- sync soul <-> raw JSON ---------- */
  const onSoulChange = (updated: SoulData) => {
    setSoul(updated);
    setRawJson(JSON.stringify(updated, null, 2));
  };

  const applyRawJson = () => {
    try {
      const parsed = JSON.parse(rawJson);
      setSoul(parsed);
      setError(null);
    } catch {
      setError('Invalid JSON');
    }
  };

  /* ---------- generate ---------- */
  const generate = async () => {
    if (!selectedAgent || !description.trim()) {
      setError('Select an agent and enter a description first.');
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const result = await api.post<{ soul: SoulData; preview: string; saved?: boolean; version_num?: number }>(
        `/agents/${selectedAgent}/soul/generate`,
        { description, save: saveAfterGenerate }
      );
      onSoulChange(result.soul);
      setPreview(result.preview ?? '');
      if (saveAfterGenerate) await loadHistory(selectedAgent);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  /* ---------- preview ---------- */
  const previewSoul = async () => {
    if (!selectedAgent) { setError('Select an agent first.'); return; }
    setPreviewing(true);
    try {
      const result = await api.post<{ preview: string }>(`/agents/${selectedAgent}/soul/preview`, { soul });
      setPreview(result.preview);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Preview failed');
    } finally {
      setPreviewing(false);
    }
  };

  /* ---------- restore ---------- */
  const restoreVersion = async (versionNum: number) => {
    if (!selectedAgent || !confirm(`Restore version ${versionNum}?`)) return;
    try {
      await api.post(`/agents/${selectedAgent}/soul/restore/${versionNum}`, {});
      const version = await api.get<SoulVersion>(`/agents/${selectedAgent}/soul/history/${versionNum}`);
      if (version.soul_json) onSoulChange(version.soul_json);
      await loadHistory(selectedAgent);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Restore failed');
    }
  };

  /* ---------- save manually ---------- */
  const saveCurrent = async () => {
    if (!selectedAgent) { setError('Select an agent first.'); return; }
    try {
      // Preview ensures soul is applied to agent config on backend; save via generate endpoint w/o description
      await api.post(`/agents/${selectedAgent}/soul/generate`, { description: '(manual save)', save: true });
      // Better: use preview route to just validate, then save current soul fields to agent via existing PATCH /agents/{id}
      // For now, wrap soul fields into PATCH
      await api.patch(`/agents/${selectedAgent}`, { soul: soul });
      await loadHistory(selectedAgent);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Save failed');
    }
  };

  /* ----------------------------------------------------------------------- */
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <h1 style={{ margin: '0 0 20px 0', fontSize: 22, color: 'var(--color-on-surface)' }}>Soul Editor</h1>

      {/* Agent selector */}
      <div style={{ ...cardStyle, marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <label style={{ ...labelStyle, margin: 0, whiteSpace: 'nowrap' }}>Agent:</label>
        <select
          style={{ ...inputStyle, maxWidth: 320 }}
          value={selectedAgent}
          onChange={e => setSelectedAgent(e.target.value)}
        >
          <option value="">— select agent —</option>
          {agents.map(a => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
        </select>
      </div>

      {error && <p style={{ color: '#ef4444', marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>

        {/* === LEFT COLUMN: Generate + Edit === */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* LLM Generation */}
          <div style={cardStyle}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: 15, color: 'var(--color-on-surface)' }}>Generate from Description</h3>
            <label style={labelStyle}>Describe the agent's personality and role:</label>
            <textarea
              style={{ ...textareaStyle, minHeight: 80 }}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="A professional, precise technical assistant that communicates concisely and prefers accuracy over friendliness..."
            />
            <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
              <button style={btnStyle('#22c55e')} onClick={generate} disabled={generating}>
                {generating ? 'Generating…' : '✦ Generate Soul'}
              </button>
              <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', color: 'var(--color-on-surface)', opacity: 0.8 }}>
                <input type="checkbox" checked={saveAfterGenerate} onChange={e => setSaveAfterGenerate(e.target.checked)} />
                Save to history
              </label>
            </div>
          </div>

          {/* Soul Fields Editor */}
          <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={{ margin: 0, fontSize: 15, color: 'var(--color-on-surface)' }}>Soul Fields</h3>
              <div style={{ display: 'flex', gap: 6 }}>
                <button style={{ ...btnStyle('#6b7280', true), background: editMode === 'fields' ? '#4a9eff' : '#6b7280' }} onClick={() => setEditMode('fields')}>Fields</button>
                <button style={{ ...btnStyle('#6b7280', true), background: editMode === 'json' ? '#4a9eff' : '#6b7280' }} onClick={() => { setRawJson(JSON.stringify(soul, null, 2)); setEditMode('json'); }}>JSON</button>
              </div>
            </div>

            {editMode === 'fields' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div>
                  <label style={labelStyle}>Persona</label>
                  <input style={inputStyle} value={(soul.persona ?? '') as string} onChange={e => onSoulChange({ ...soul, persona: e.target.value })} placeholder="A helpful expert assistant" />
                </div>
                <div>
                  <label style={labelStyle}>Tone</label>
                  <input style={inputStyle} value={(soul.tone ?? '') as string} onChange={e => onSoulChange({ ...soul, tone: e.target.value })} placeholder="professional, precise, friendly" />
                </div>
                <div>
                  <label style={labelStyle}>Communication Style</label>
                  <input style={inputStyle} value={(soul.communication_style ?? '') as string} onChange={e => onSoulChange({ ...soul, communication_style: e.target.value })} placeholder="concise, well-structured, uses headers" />
                </div>
                <div>
                  <label style={labelStyle}>Core Values (one per line)</label>
                  <textarea
                    style={{ ...textareaStyle, minHeight: 70 }}
                    value={((soul.core_values ?? []) as string[]).join('\n')}
                    onChange={e => onSoulChange({ ...soul, core_values: e.target.value.split('\n').filter(Boolean) })}
                    placeholder="accuracy&#10;helpfulness&#10;transparency"
                  />
                </div>
                <div>
                  <label style={labelStyle}>Rules (one per line)</label>
                  <textarea
                    style={{ ...textareaStyle, minHeight: 90 }}
                    value={((soul.rules ?? []) as string[]).join('\n')}
                    onChange={e => onSoulChange({ ...soul, rules: e.target.value.split('\n').filter(Boolean) })}
                    placeholder="Never fabricate citations&#10;Always acknowledge uncertainty"
                  />
                </div>
              </div>
            ) : (
              <div>
                <textarea
                  style={{ ...textareaStyle, minHeight: 220 }}
                  value={rawJson}
                  onChange={e => setRawJson(e.target.value)}
                  spellCheck={false}
                />
                <button style={{ ...btnStyle(), marginTop: 8 }} onClick={applyRawJson}>Apply JSON</button>
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button style={btnStyle('#4a9eff')} onClick={previewSoul} disabled={previewing}>
                {previewing ? 'Previewing…' : 'Preview'}
              </button>
            </div>
          </div>
        </div>

        {/* === RIGHT COLUMN: Preview + History === */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* System Prompt Preview */}
          <div style={cardStyle}>
            <h3 style={{ margin: '0 0 10px 0', fontSize: 15, color: 'var(--color-on-surface)' }}>System Prompt Preview</h3>
            {preview ? (
              <pre style={{
                margin: 0, fontSize: 12, lineHeight: 1.55,
                color: 'var(--color-on-surface)', opacity: 0.85,
                whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto',
                background: 'var(--color-bg)', padding: 12, borderRadius: 6,
                border: '1px solid var(--color-border)',
              }}>
                {preview}
              </pre>
            ) : (
              <p style={{ margin: 0, color: 'var(--color-on-surface)', opacity: 0.4, fontSize: 13 }}>
                Click "Preview" after editing the soul fields to see the rendered system prompt.
              </p>
            )}
          </div>

          {/* Version History */}
          <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <h3 style={{ margin: 0, fontSize: 15, color: 'var(--color-on-surface)' }}>Version History</h3>
              {selectedAgent && (
                <button style={btnStyle('#6b7280', true)} onClick={() => loadHistory(selectedAgent)} disabled={historyLoading}>
                  {historyLoading ? '…' : 'Refresh'}
                </button>
              )}
            </div>
            {!selectedAgent && (
              <p style={{ margin: 0, fontSize: 13, color: 'var(--color-on-surface)', opacity: 0.4 }}>Select an agent to view history.</p>
            )}
            {selectedAgent && history.length === 0 && !historyLoading && (
              <p style={{ margin: 0, fontSize: 13, color: 'var(--color-on-surface)', opacity: 0.4 }}>No saved versions yet.</p>
            )}
            {history.map(v => (
              <div key={v.version_id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 0', borderBottom: '1px solid var(--color-border)',
              }}>
                <div>
                  <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-on-surface)' }}>
                    v{v.version_num}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--color-on-surface)', opacity: 0.55, marginLeft: 10 }}>
                    {new Date(v.created_at).toLocaleString()}
                  </span>
                  {v.change_note && (
                    <span style={{ fontSize: 11, color: 'var(--color-on-surface)', opacity: 0.6, marginLeft: 8 }}>
                      — {v.change_note}
                    </span>
                  )}
                </div>
                <button style={btnStyle('#f59e0b', true)} onClick={() => restoreVersion(v.version_num)}>
                  Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
