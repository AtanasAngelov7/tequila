// Sprint 04 — Agent card component
import React from 'react';
import type { AgentConfig } from '../../hooks/useAgents';

interface AgentCardProps {
  agent: AgentConfig;
  onEdit: (agent: AgentConfig) => void;
  onEditSoul: (agent: AgentConfig) => void;
  onClone: (agent: AgentConfig) => void;
  onDelete: (agent: AgentConfig) => void;
}

const cardStyle: React.CSSProperties = {
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: '16px',
  backgroundColor: 'var(--color-surface)',
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
};

const tagStyle: React.CSSProperties = {
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: 4,
  fontSize: 11,
  fontWeight: 600,
  backgroundColor: 'var(--color-primary, #6366f1)',
  color: '#fff',
};

const statusDot = (status: string): React.CSSProperties => ({
  width: 8,
  height: 8,
  borderRadius: '50%',
  display: 'inline-block',
  backgroundColor: status === 'active' ? '#22c55e' : '#ef4444',
  marginRight: 4,
});

const btnStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderRadius: 4,
  border: '1px solid var(--color-border)',
  background: 'transparent',
  cursor: 'pointer',
  fontSize: 12,
  color: 'var(--color-on-surface)',
};

const dangerBtnStyle: React.CSSProperties = {
  ...btnStyle,
  color: '#ef4444',
  borderColor: '#ef4444',
};

export default function AgentCard({ agent, onEdit, onEditSoul, onClone, onDelete }: AgentCardProps) {
  const persona = agent.soul?.persona || agent.persona || '—';

  return (
    <div style={cardStyle}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 600, fontSize: 15 }}>{agent.name}</span>
        <span style={tagStyle}>{agent.role}</span>
      </div>

      {/* Status + model */}
      <div style={{ fontSize: 12, color: 'var(--color-on-surface)', opacity: 0.7 }}>
        <span style={statusDot(agent.status)} />
        {agent.status} &nbsp;·&nbsp; {agent.default_model}
        {agent.is_admin && <span style={{ ...tagStyle, marginLeft: 6, backgroundColor: '#f59e0b' }}>admin</span>}
      </div>

      {/* Persona preview */}
      <div
        style={{
          fontSize: 13,
          color: 'var(--color-on-surface)',
          opacity: 0.85,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={persona}
      >
        {persona}
      </div>

      {/* Tools / skills summary */}
      {(agent.tools.length > 0 || agent.skills.length > 0) && (
        <div style={{ fontSize: 11, opacity: 0.6 }}>
          {agent.tools.length > 0 && <span>Tools: {agent.tools.length} &nbsp;</span>}
          {agent.skills.length > 0 && <span>Skills: {agent.skills.length}</span>}
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
        <button style={btnStyle} onClick={() => onEdit(agent)}>Edit</button>
        <button style={btnStyle} onClick={() => onEditSoul(agent)}>Soul</button>
        <button style={btnStyle} onClick={() => onClone(agent)}>Clone</button>
        <button style={dangerBtnStyle} onClick={() => onDelete(agent)}>Delete</button>
      </div>
    </div>
  );
}
