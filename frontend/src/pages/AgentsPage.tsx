// Sprint 04 — Agent management page
import React, { useState } from 'react';
import { useAgents, type AgentConfig, type SoulConfig } from '../hooks/useAgents';
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
  default_model: 'anthropic:claude-sonnet-4-5',
  persona: 'a helpful AI assistant',
  role: 'main',
};

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

export default function AgentsPage() {
  const { agents, loading, error, createAgent, deleteAgent, cloneAgent, updateSoul } = useAgents();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateForm>(defaultForm);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [soulTarget, setSoulTarget] = useState<AgentConfig | null>(null);

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
            onEdit={() => {/* edit inline via soul editor for now */}}
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
                style={inputStyle}
                value={form.default_model}
                onChange={(e) => setForm((f) => ({ ...f, default_model: e.target.value }))}
                placeholder="anthropic:claude-sonnet-4-5"
              />
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
