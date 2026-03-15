// Sprint 04 — Soul configuration editor modal
import React, { useState, useEffect } from 'react';
import type { AgentConfig, SoulConfig } from '../../hooks/useAgents';

interface SoulEditorProps {
  agent: AgentConfig;
  onSave: (agentId: string, version: number, soul: Partial<SoulConfig>) => Promise<void>;
  onClose: () => void;
}

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0,0,0,0.5)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
};

const modalStyle: React.CSSProperties = {
  backgroundColor: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: 24,
  width: '100%',
  maxWidth: 600,
  maxHeight: '85vh',
  overflowY: 'auto',
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  marginBottom: 4,
  display: 'block',
  color: 'var(--color-on-surface)',
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

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  resize: 'vertical',
  minHeight: 80,
  fontFamily: 'monospace',
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

const btnSecondary: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 4,
  border: '1px solid var(--color-border)',
  backgroundColor: 'transparent',
  color: 'var(--color-on-surface)',
  cursor: 'pointer',
  fontSize: 13,
};

export default function SoulEditor({ agent, onSave, onClose }: SoulEditorProps) {
  const soul = agent.soul ?? { persona: agent.persona, instructions: '' };

  const [persona, setPersona] = useState(soul.persona ?? '');
  const [instructions, setInstructions] = useState(soul.instructions ?? '');
  const [tone, setTone] = useState(soul.tone ?? 'neutral');
  const [verbosity, setVerbosity] = useState(soul.verbosity ?? 'normal');
  const [preferMarkdown, setPreferMarkdown] = useState(soul.prefer_markdown ?? true);
  const [emojiUsage, setEmojiUsage] = useState(soul.emoji_usage ?? false);
  const [refuseTopics, setRefuseTopics] = useState((soul.refuse_topics ?? []).join(', '));
  const [escalationPhrases, setEscalationPhrases] = useState(
    (soul.escalation_phrases ?? []).join(', '),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(agent.agent_id, agent.version, {
        persona,
        instructions,
        tone,
        verbosity,
        prefer_markdown: preferMarkdown,
        emoji_usage: emojiUsage,
        refuse_topics: refuseTopics.split(',').map((s) => s.trim()).filter(Boolean),
        escalation_phrases: escalationPhrases.split(',').map((s) => s.trim()).filter(Boolean),
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div style={overlayStyle} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={modalStyle} role="dialog" aria-modal="true" aria-label="Soul Editor">
        <div style={{ fontSize: 16, fontWeight: 700 }}>Soul Editor — {agent.name}</div>

        <div>
          <label style={labelStyle}>Persona</label>
          <textarea
            style={textareaStyle}
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            placeholder="Describe the agent's personality and identity..."
          />
        </div>

        <div>
          <label style={labelStyle}>Instructions</label>
          <textarea
            style={{ ...textareaStyle, minHeight: 120 }}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Behavioural rules, constraints, and guidelines..."
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label style={labelStyle}>Tone</label>
            <select
              style={inputStyle}
              value={tone}
              onChange={(e) => setTone(e.target.value)}
            >
              {['neutral', 'formal', 'casual', 'friendly', 'professional', 'concise'].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Verbosity</label>
            <select
              style={inputStyle}
              value={verbosity}
              onChange={(e) => setVerbosity(e.target.value)}
            >
              {['terse', 'normal', 'verbose', 'exhaustive'].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 20 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={preferMarkdown}
              onChange={(e) => setPreferMarkdown(e.target.checked)}
            />
            Prefer Markdown
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={emojiUsage}
              onChange={(e) => setEmojiUsage(e.target.checked)}
            />
            Allow Emoji
          </label>
        </div>

        <div>
          <label style={labelStyle}>Refuse Topics (comma-separated)</label>
          <input
            style={inputStyle}
            value={refuseTopics}
            onChange={(e) => setRefuseTopics(e.target.value)}
            placeholder="e.g. violence, illegal activities"
          />
        </div>

        <div>
          <label style={labelStyle}>Escalation Phrases (comma-separated)</label>
          <input
            style={inputStyle}
            value={escalationPhrases}
            onChange={(e) => setEscalationPhrases(e.target.value)}
            placeholder="e.g. transfer to human, speak to an agent"
          />
        </div>

        {error && (
          <div style={{ color: '#ef4444', fontSize: 12, padding: '6px 10px', background: '#fef2f2', borderRadius: 4 }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
          <button style={btnSecondary} onClick={onClose}>Cancel</button>
          <button style={btnPrimary} onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save Soul'}
          </button>
        </div>
      </div>
    </div>
  );
}
