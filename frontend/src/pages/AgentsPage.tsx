// Sprint 04 — Agent management page
import React, { useState, useEffect } from 'react';
import { useAgents, type AgentConfig, type SoulConfig } from '../hooks/useAgents';
import { api } from '../api/client';
import AgentCard from '../components/agent/AgentCard';
import SoulEditor from '../components/agent/SoulEditor';

const pageStyle: React.CSSProperties = {
  padding: '24px',
  overflowY: 'auto',
  height: '100%',
  boxSizing: 'border-box',
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  marginBottom: 20,
};

const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
  gap: 16,
};

const btnPrimary: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 4,
  border: 'none',
  backgroundColor: 'var(--color-primary, #6366f1)',
  color: '#fff',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: 13,
};

interface CreateForm {
  name: string;
  default_model: string;
  persona: string;
  role: string;
}

const defaultForm: CreateForm = {
  name: '',
  default_model: 'anthropic:claude-sonnet-4-6',
  persona: 'a helpful AI assistant',
  role: 'main',
};

// Grouped model options for the dropdown
const GROUPED_MODELS: { group: string; models: { id: string; name: string }[] }[] = [
  {
    group: 'Anthropic',
    models: [
      { id: 'anthropic:claude-opus-4-6', name: 'Claude Opus 4.6' },
      { id: 'anthropic:claude-sonnet-4-6', name: 'Claude Sonnet 4.6' },
      { id: 'anthropic:claude-haiku-4-5', name: 'Claude Haiku 4.5' },
    ],
  },
  {
    group: 'OpenAI',
    models: [
      { id: 'openai:gpt-5.4', name: 'GPT-5.4' },
      { id: 'openai:gpt-5.4-mini', name: 'GPT-5.4 Mini' },
      { id: 'openai:gpt-5.4-nano', name: 'GPT-5.4 Nano' },
    ],
  },
  {
    group: 'Google Gemini',
    models: [
      { id: 'gemini:gemini-2.5-pro', name: 'Gemini 2.5 Pro' },
      { id: 'gemini:gemini-2.5-flash', name: 'Gemini 2.5 Flash' },
      { id: 'gemini:gemini-2.5-flash-lite', name: 'Gemini 2.5 Flash-Lite' },
    ],
  },
  {
    group: 'Anthropic (web)',
    models: [
      { id: 'anthropic_web:claude-opus-4-6', name: 'Claude Opus 4.6 (web)' },
      { id: 'anthropic_web:claude-sonnet-4-6', name: 'Claude Sonnet 4.6 (web)' },
    ],
  },
  {
    group: 'OpenAI (web)',
    models: [
      { id: 'openai_web:gpt-5.4', name: 'GPT-5.4 (web)' },
      { id: 'openai_web:gpt-5.4-mini', name: 'GPT-5.4 Mini (web)' },
    ],
  },
  {
    group: 'Gemini (web)',
    models: [
      { id: 'gemini_web:gemini-2.5-pro', name: 'Gemini 2.5 Pro (web)' },
      { id: 'gemini_web:gemini-2.5-flash', name: 'Gemini 2.5 Flash (web)' },
    ],
  },
  {
    group: 'Ollama (local)',
    models: [
      { id: 'ollama:llama3', name: 'Llama 3' },
      { id: 'ollama:mistral', name: 'Mistral' },
      { id: 'ollama:phi3', name: 'Phi-3' },
    ],
  },
];

// Flat list of all known model IDs for validation
const ALL_KNOWN_MODEL_IDS = new Set(
  GROUPED_MODELS.flatMap((g) => g.models.map((m) => m.id))
);

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0,0,0,0.5)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 999,
};

const modalStyle: React.CSSProperties = {
  backgroundColor: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: 24,
  width: '100%',
  maxWidth: 480,
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  marginBottom: 4,
  display: 'block',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: 4,
  border: '1px solid var(--color-border)',
  backgroundColor: 'var(--color-input-bg, var(--color-surface))',
  color: 'var(--color-on-surface)',
  fontSize: 13,
  boxSizing: 'border-box',
};

interface EditForm {
  name: string;
  default_model: string;
  persona: string;
  role: string;
}

export default function AgentsPage() {
  const { agents, loading, error, createAgent, updateAgent, deleteAgent, cloneAgent, updateSoul } = useAgents();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateForm>(defaultForm);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [soulTarget, setSoulTarget] = useState<AgentConfig | null>(null);
  const [modelFilter, setModelFilter] = useState('');
  const [providerHealth, setProviderHealth] = useState<Record<string, boolean>>({});

  // Edit modal state
  const [editTarget, setEditTarget] = useState<AgentConfig | null>(null);
  const [editForm, setEditForm] = useState<EditForm>({ name: '', default_model: '', persona: '', role: 'main' });
  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [editModelFilter, setEditModelFilter] = useState('');

  useEffect(() => {
    api.get<{ providers: Array<{ provider_id: string; healthy: boolean }> }>('/providers')
      .then((data) => {
        const map: Record<string, boolean> = {};
        for (const p of data.providers) map[p.provider_id] = p.healthy;
        setProviderHealth(map);
      })
      .catch(() => {/* ignore — warning simply won't show */});
  }, []);

  const handleCreate = async () => {
    if (!form.name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      await createAgent({
        name: form.name.trim(),
        default_model: form.default_model,
        persona: form.persona,
        role: form.role,
      });
      setForm(defaultForm);
      setShowCreate(false);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (agent: AgentConfig) => {
    if (!confirm(`Delete agent "${agent.name}"?`)) return;
    try {
      await deleteAgent(agent.agent_id);
    } catch (e) {
      alert(String(e));
    }
  };

  const handleClone = async (agent: AgentConfig) => {
    try {
      await cloneAgent(agent.agent_id);
    } catch (e) {
      alert(String(e));
    }
  };

  const handleSaveSoul = async (agentId: string, version: number, soul: Partial<SoulConfig>) => {
    await updateSoul(agentId, version, soul);
  };

  const openEditModal = (agent: AgentConfig) => {
    setEditTarget(agent);
    setEditForm({
      name: agent.name,
      default_model: agent.default_model,
      persona: agent.soul?.persona || agent.persona || '',
      role: agent.role,
    });
    setEditError(null);
    setEditModelFilter('');
  };

  const handleEdit = async () => {
    if (!editTarget) return;
    setEditing(true);
    setEditError(null);
    try {
      await updateAgent(editTarget.agent_id, {
        version: editTarget.version,
        name: editForm.name.trim(),
        default_model: editForm.default_model,
        persona: editForm.persona,
        role: editForm.role,
      });
      setEditTarget(null);
    } catch (e) {
      setEditError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditing(false);
    }
  };

  return (
    <div style={pageStyle}>
      <div style={headerStyle}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Agents</h2>
        <button style={btnPrimary} onClick={() => setShowCreate(true)}>+ New Agent</button>
      </div>

      {loading && (
        <div style={{ opacity: 0.5, fontSize: 14 }}>Loading agents…</div>
      )}

      {error && (
        <div style={{ color: '#ef4444', marginBottom: 16, fontSize: 13 }}>
          Error: {error}
        </div>
      )}

      {!loading && agents.length === 0 && (
        <div style={{ opacity: 0.5, fontSize: 14, textAlign: 'center', marginTop: 60 }}>
          No agents yet. Create one to get started.
        </div>
      )}

      <div style={gridStyle}>
        {agents.map((agent) => (
          <AgentCard
            key={agent.agent_id}
            agent={agent}
            onEdit={openEditModal}
            onEditSoul={setSoulTarget}
            onClone={handleClone}
            onDelete={handleDelete}
          />
        ))}
      </div>

      {/* Create modal */}
      {showCreate && (
        <div style={overlayStyle} onClick={(e) => e.target === e.currentTarget && setShowCreate(false)}>
          <div style={modalStyle}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>New Agent</div>

            <div>
              <label style={labelStyle}>Name *</label>
              <input
                style={inputStyle}
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Support Bot"
                autoFocus
              />
            </div>

            <div>
              <label style={labelStyle}>Default Model</label>
              <input
                style={{ ...inputStyle, marginBottom: 4 }}
                placeholder="Filter models…"
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
              />
              <select
                style={inputStyle}
                value={ALL_KNOWN_MODEL_IDS.has(form.default_model) ? form.default_model : ''}
                onChange={(e) => {
                  if (e.target.value) setForm((f) => ({ ...f, default_model: e.target.value }));
                }}
              >
                {!ALL_KNOWN_MODEL_IDS.has(form.default_model) && (
                  <option value="" disabled>
                    {form.default_model} (custom)
                  </option>
                )}
                {GROUPED_MODELS.map((group) => {
                  const filtered = group.models.filter((m) =>
                    !modelFilter || m.name.toLowerCase().includes(modelFilter.toLowerCase()) || m.id.toLowerCase().includes(modelFilter.toLowerCase())
                  );
                  if (filtered.length === 0) return null;
                  return (
                    <optgroup key={group.group} label={group.group}>
                      {filtered.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </optgroup>
                  );
                })}
              </select>
              {(() => {
                const providerPrefix = form.default_model.split(':')[0];
                if (providerHealth[providerPrefix] === false) {
                  return (
                    <div style={{ color: '#f59e0b', fontSize: 12, marginTop: 4 }}>
                      ⚠ This model&apos;s provider is not configured
                    </div>
                  );
                }
                return null;
              })()}
            </div>

            <div>
              <label style={labelStyle}>Persona</label>
              <input
                style={inputStyle}
                value={form.persona}
                onChange={(e) => setForm((f) => ({ ...f, persona: e.target.value }))}
              />
            </div>

            <div>
              <label style={labelStyle}>Role</label>
              <select
                style={inputStyle}
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
              >
                {['main', 'support', 'analyst', 'cron', 'webhook'].map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>

            {createError && (
              <div style={{ color: '#ef4444', fontSize: 12 }}>{createError}</div>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                style={{
                  padding: '8px 16px', borderRadius: 4, border: '1px solid var(--color-border)',
                  background: 'transparent', color: 'var(--color-on-surface)', cursor: 'pointer', fontSize: 13,
                }}
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </button>
              <button style={btnPrimary} onClick={handleCreate} disabled={creating}>
                {creating ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit modal */}
      {editTarget && (
        <div style={overlayStyle} onClick={(e) => e.target === e.currentTarget && setEditTarget(null)}>
          <div style={modalStyle}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Edit Agent</div>

            <div>
              <label style={labelStyle}>Name</label>
              <input
                style={inputStyle}
                value={editForm.name}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                autoFocus
              />
            </div>

            <div>
              <label style={labelStyle}>Default Model</label>
              <input
                style={{ ...inputStyle, marginBottom: 4 }}
                placeholder="Filter models…"
                value={editModelFilter}
                onChange={(e) => setEditModelFilter(e.target.value)}
              />
              <select
                style={inputStyle}
                value={ALL_KNOWN_MODEL_IDS.has(editForm.default_model) ? editForm.default_model : ''}
                onChange={(e) => {
                  if (e.target.value) setEditForm((f) => ({ ...f, default_model: e.target.value }));
                }}
              >
                {!ALL_KNOWN_MODEL_IDS.has(editForm.default_model) && (
                  <option value="" disabled>
                    {editForm.default_model} (custom)
                  </option>
                )}
                {GROUPED_MODELS.map((group) => {
                  const filtered = group.models.filter((m) =>
                    !editModelFilter || m.name.toLowerCase().includes(editModelFilter.toLowerCase()) || m.id.toLowerCase().includes(editModelFilter.toLowerCase())
                  );
                  if (filtered.length === 0) return null;
                  return (
                    <optgroup key={group.group} label={group.group}>
                      {filtered.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </optgroup>
                  );
                })}
              </select>
              {(() => {
                const providerPrefix = editForm.default_model.split(':')[0];
                if (providerHealth[providerPrefix] === false) {
                  return (
                    <div style={{ color: '#f59e0b', fontSize: 12, marginTop: 4 }}>
                      ⚠ This model&apos;s provider is not configured
                    </div>
                  );
                }
                return null;
              })()}
            </div>

            <div>
              <label style={labelStyle}>Persona</label>
              <input
                style={inputStyle}
                value={editForm.persona}
                onChange={(e) => setEditForm((f) => ({ ...f, persona: e.target.value }))}
              />
            </div>

            <div>
              <label style={labelStyle}>Role</label>
              <select
                style={inputStyle}
                value={editForm.role}
                onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}
              >
                {['main', 'support', 'analyst', 'cron', 'webhook'].map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>

            {editError && (
              <div style={{ color: '#ef4444', fontSize: 12 }}>{editError}</div>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                style={{
                  padding: '8px 16px', borderRadius: 4, border: '1px solid var(--color-border)',
                  background: 'transparent', color: 'var(--color-on-surface)', cursor: 'pointer', fontSize: 13,
                }}
                onClick={() => setEditTarget(null)}
              >
                Cancel
              </button>
              <button style={btnPrimary} onClick={handleEdit} disabled={editing}>
                {editing ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Soul editor modal */}
      {soulTarget && (
        <SoulEditor
          agent={soulTarget}
          onSave={handleSaveSoul}
          onClose={() => setSoulTarget(null)}
        />
      )}
    </div>
  );
}
