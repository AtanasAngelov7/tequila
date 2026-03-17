/**
 * SkillManagerPage — Browse, create, edit and assign skills (Sprint 14a §4.5.5).
 *
 * Accessible via the /skills route.
 * Features:
 *   - List all skills with search + tag filter
 *   - Create / edit skills with tabs: Summary | Instructions | Resources
 *   - Assign skills to agents
 *   - Import / export as JSON v1.1
 *   - Clone skills
 */
import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';

interface SkillDef {
  skill_id: string;
  name: string;
  description: string;
  version: string;
  summary: string;
  instructions: string;
  required_tools: string[];
  recommended_tools: string[];
  activation_mode: 'always' | 'trigger' | 'manual';
  trigger_patterns: string[];
  trigger_tool_presence: string[];
  priority: number;
  tags: string[];
  author: string;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

interface SkillResource {
  resource_id: string;
  skill_id: string;
  name: string;
  description: string;
  content: string;
}

type Tab = 'summary' | 'instructions' | 'resources';

const cardStyle: React.CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: '16px',
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
};

const btnStyle = (color = '#4a9eff', small = false): React.CSSProperties => ({
  padding: small ? '4px 10px' : '7px 14px',
  borderRadius: 5,
  border: 'none',
  background: color,
  color: '#fff',
  cursor: 'pointer',
  fontSize: small ? 11 : 13,
  fontWeight: 600,
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
  minHeight: 100,
  fontFamily: 'monospace',
};

const ACTIVATION_COLORS: Record<string, string> = {
  always: '#22c55e',
  trigger: '#4a9eff',
  manual: '#f59e0b',
};

export default function SkillManagerPage() {
  const [skills, setSkills] = useState<SkillDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<Partial<SkillDef> | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('summary');
  const [resources, setResources] = useState<SkillResource[]>([]);
  const [savingSkill, setSavingSkill] = useState(false);
  const [importText, setImportText] = useState('');
  const [showImport, setShowImport] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<SkillDef[]>('/skills');
      setSkills(data);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? 'Failed to load skills');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openNew = () => {
    setEditing({
      name: '',
      description: '',
      summary: '',
      instructions: '',
      activation_mode: 'trigger',
      trigger_patterns: [],
      required_tools: [],
      recommended_tools: [],
      trigger_tool_presence: [],
      priority: 100,
      tags: [],
      author: 'user',
    });
    setIsNew(true);
    setActiveTab('summary');
    setResources([]);
  };

  const openEdit = async (skill: SkillDef) => {
    setEditing({ ...skill });
    setIsNew(false);
    setActiveTab('summary');
    try {
      const res = await api.get<SkillResource[]>(`/skills/${skill.skill_id}/resources`);
      setResources(res);
    } catch {
      setResources([]);
    }
  };

  const saveSkill = async () => {
    if (!editing) return;
    setSavingSkill(true);
    try {
      if (isNew) {
        await api.post('/skills', editing);
      } else {
        await api.patch(`/skills/${editing.skill_id}`, editing);
      }
      await load();
      setEditing(null);
    } catch (err: unknown) {
      alert((err as { message?: string })?.message ?? 'Save failed');
    } finally {
      setSavingSkill(false);
    }
  };

  const deleteSkill = async (skill: SkillDef) => {
    if (!confirm(`Delete skill "${skill.name}"?`)) return;
    try {
      await api.delete(`/skills/${skill.skill_id}`);
      await load();
    } catch (err: unknown) {
      alert((err as { message?: string })?.message ?? 'Delete failed');
    }
  };

  const cloneSkill = async (skill: SkillDef) => {
    try {
      await api.post(`/skills/${skill.skill_id}/clone`, {});
      await load();
    } catch (err: unknown) {
      alert((err as { message?: string })?.message ?? 'Clone failed');
    }
  };

  const exportSkill = async (skill: SkillDef) => {
    try {
      const data = await api.get(`/skills/${skill.skill_id}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${skill.name.replace(/\s+/g, '_')}.skill.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      alert('Export failed');
    }
  };

  const importSkill = async () => {
    try {
      const data = JSON.parse(importText);
      await api.post('/skills/import', { data });
      setShowImport(false);
      setImportText('');
      await load();
    } catch (err: unknown) {
      alert((err as { message?: string })?.message ?? 'Import failed — check JSON format');
    }
  };

  const addResource = async () => {
    if (!editing?.skill_id) return;
    const name = prompt('Resource name:');
    if (!name) return;
    const content = prompt('Resource content (markdown):');
    if (!content) return;
    await api.post(`/skills/${editing.skill_id}/resources`, { name, content });
    const res = await api.get<SkillResource[]>(`/skills/${editing.skill_id}/resources`);
    setResources(res);
  };

  const deleteResource = async (resourceId: string) => {
    if (!editing?.skill_id) return;
    if (!confirm('Delete this resource?')) return;
    await api.delete(`/skills/${editing.skill_id}/resources/${resourceId}`);
    setResources(resources.filter(r => r.resource_id !== resourceId));
  };

  const filtered = skills.filter(s =>
    !search || s.name.toLowerCase().includes(search.toLowerCase()) ||
    s.description.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22, color: 'var(--color-on-surface)' }}>Skills</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={btnStyle('#6b7280')} onClick={() => setShowImport(!showImport)}>
            Import
          </button>
          <button style={btnStyle()} onClick={openNew}>+ New Skill</button>
        </div>
      </div>

      {/* Import panel */}
      {showImport && (
        <div style={{ ...cardStyle, marginBottom: 16 }}>
          <p style={{ margin: 0, color: 'var(--color-on-surface)', opacity: 0.7, fontSize: 13 }}>
            Paste a v1.0 or v1.1 JSON skill payload:
          </p>
          <textarea
            style={{ ...textareaStyle, height: 120 }}
            value={importText}
            onChange={e => setImportText(e.target.value)}
            placeholder='{"version": "1.1", "name": "...", ...}'
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={btnStyle()} onClick={importSkill}>Import</button>
            <button style={btnStyle('#6b7280')} onClick={() => setShowImport(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Search */}
      <input
        style={{ ...inputStyle, marginBottom: 16 }}
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search skills…"
      />

      {loading && <p style={{ color: 'var(--color-on-surface)', opacity: 0.6 }}>Loading…</p>}
      {error && <p style={{ color: '#ef4444' }}>{error}</p>}

      {/* Skill list */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
        {filtered.map(skill => (
          <div key={skill.skill_id} style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-on-surface)' }}>{skill.name}</span>
                {skill.is_builtin && (
                  <span style={{ marginLeft: 8, fontSize: 10, background: '#4a9eff22', color: '#4a9eff', padding: '1px 6px', borderRadius: 4, fontWeight: 600 }}>
                    built-in
                  </span>
                )}
              </div>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                background: `${ACTIVATION_COLORS[skill.activation_mode] ?? '#888'}22`,
                color: ACTIVATION_COLORS[skill.activation_mode] ?? '#888',
              }}>
                {skill.activation_mode}
              </span>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>{skill.description}</p>
            {skill.tags.length > 0 && (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {skill.tags.map(t => (
                  <span key={t} style={{ fontSize: 10, background: 'var(--color-surface-alt, #333)', padding: '1px 6px', borderRadius: 4, color: 'var(--color-on-surface)', opacity: 0.8 }}>
                    {t}
                  </span>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <button style={btnStyle('#4a9eff', true)} onClick={() => openEdit(skill)}>Edit</button>
              <button style={btnStyle('#6b7280', true)} onClick={() => cloneSkill(skill)}>Clone</button>
              <button style={btnStyle('#6b7280', true)} onClick={() => exportSkill(skill)}>Export</button>
              {!skill.is_builtin && (
                <button style={btnStyle('#ef4444', true)} onClick={() => deleteSkill(skill)}>Delete</button>
              )}
            </div>
          </div>
        ))}
        {!loading && filtered.length === 0 && (
          <p style={{ color: 'var(--color-on-surface)', opacity: 0.5, gridColumn: '1/-1' }}>No skills found.</p>
        )}
      </div>

      {/* Edit / Create modal */}
      {editing && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--color-bg)', border: '1px solid var(--color-border)',
            borderRadius: 10, padding: 24, width: 640, maxHeight: '85vh',
            overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12,
          }}>
            <h2 style={{ margin: 0, fontSize: 18, color: 'var(--color-on-surface)' }}>
              {isNew ? 'New Skill' : `Edit: ${editing.name}`}
            </h2>

            {/* Tabs */}
            <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--color-border)', paddingBottom: 8 }}>
              {(['summary', 'instructions', 'resources'] as Tab[]).map(tab => (
                <button key={tab} style={{
                  padding: '5px 14px', borderRadius: '5px 5px 0 0', border: 'none', cursor: 'pointer',
                  background: activeTab === tab ? '#4a9eff' : 'transparent',
                  color: activeTab === tab ? '#fff' : 'var(--color-on-surface)',
                  fontWeight: 600, fontSize: 13, opacity: activeTab === tab ? 1 : 0.6,
                }} onClick={() => setActiveTab(tab)}>
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>

            {activeTab === 'summary' && (
              <>
                <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>Name *</label>
                <input style={inputStyle} value={editing.name ?? ''} onChange={e => setEditing({ ...editing, name: e.target.value })} />

                <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>Description</label>
                <input style={inputStyle} value={editing.description ?? ''} onChange={e => setEditing({ ...editing, description: e.target.value })} />

                <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>
                  Summary (Level 1 — shown in every prompt, ~20–50 tokens)
                </label>
                <textarea style={textareaStyle} value={editing.summary ?? ''} onChange={e => setEditing({ ...editing, summary: e.target.value })} />

                <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>Activation Mode</label>
                <select style={inputStyle} value={editing.activation_mode ?? 'trigger'} onChange={e => setEditing({ ...editing, activation_mode: e.target.value as SkillDef['activation_mode'] })}>
                  <option value="always">always — always active</option>
                  <option value="trigger">trigger — activated by regex match</option>
                  <option value="manual">manual — activated by agent/user</option>
                </select>

                {editing.activation_mode === 'trigger' && (
                  <>
                    <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>
                      Trigger Patterns (one regex per line)
                    </label>
                    <textarea
                      style={textareaStyle}
                      value={(editing.trigger_patterns ?? []).join('\n')}
                      onChange={e => setEditing({ ...editing, trigger_patterns: e.target.value.split('\n').filter(Boolean) })}
                      placeholder="review.*code&#10;PR review"
                    />
                  </>
                )}

                <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>Priority (lower = higher priority)</label>
                <input style={inputStyle} type="number" value={editing.priority ?? 100} onChange={e => setEditing({ ...editing, priority: parseInt(e.target.value) })} />

                <label style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>Tags (comma-separated)</label>
                <input style={inputStyle} value={(editing.tags ?? []).join(', ')} onChange={e => setEditing({ ...editing, tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean) })} />
              </>
            )}

            {activeTab === 'instructions' && (
              <>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.6 }}>
                  Level 2 instructions — injected into the system prompt when the skill is active. Markdown supported.
                </p>
                <textarea
                  style={{ ...textareaStyle, minHeight: 300 }}
                  value={editing.instructions ?? ''}
                  onChange={e => setEditing({ ...editing, instructions: e.target.value })}
                  placeholder="## Skill Instructions&#10;&#10;When asked to..., follow these steps:&#10;1. ..."
                />
              </>
            )}

            {activeTab === 'resources' && (
              <>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.6 }}>
                  Level 3 resources — reference material fetched on-demand by the agent via <code>skill_read_resource</code>.
                </p>
                {resources.map(r => (
                  <div key={r.resource_id} style={{ ...cardStyle, gap: 6 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--color-on-surface)' }}>{r.name}</span>
                      <button style={btnStyle('#ef4444', true)} onClick={() => deleteResource(r.resource_id)}>
                        Delete
                      </button>
                    </div>
                    <p style={{ margin: 0, fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.6 }}>{r.description}</p>
                    <pre style={{ margin: 0, fontSize: 11, background: 'var(--color-surface)', padding: 8, borderRadius: 4, overflow: 'auto', maxHeight: 120 }}>
                      {r.content.slice(0, 500)}{r.content.length > 500 ? '…' : ''}
                    </pre>
                  </div>
                ))}
                {!isNew && (
                  <button style={btnStyle('#22c55e')} onClick={addResource}>+ Add Resource</button>
                )}
                {isNew && (
                  <p style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.5 }}>
                    Save the skill first, then add resources.
                  </p>
                )}
              </>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
              <button style={btnStyle('#6b7280')} onClick={() => setEditing(null)}>Cancel</button>
              <button style={btnStyle()} onClick={saveSkill} disabled={savingSkill}>
                {savingSkill ? 'Saving…' : 'Save Skill'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
