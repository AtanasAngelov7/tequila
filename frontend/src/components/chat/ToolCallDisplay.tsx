import { useState } from 'react';
import type { ToolCallOut } from '../../types';

/**
 * ToolCallDisplay — renders one tool call record inline in a message.
 * Shows tool name, arguments, and result with expandable details.
 */
interface ToolCallDisplayProps {
  toolCall: ToolCallOut;
}

export default function ToolCallDisplay({ toolCall }: ToolCallDisplayProps) {
  const [expanded, setExpanded] = useState(false);

  const statusColor =
    toolCall.success === true
      ? 'var(--color-success, #22c55e)'
      : toolCall.success === false
        ? 'var(--color-error, #ef4444)'
        : 'var(--color-border)';

  const statusLabel =
    toolCall.success === true ? '✓' : toolCall.success === false ? '✗' : '…';

  return (
    <div
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 6,
        marginTop: 6,
        fontSize: 12,
        overflow: 'hidden',
      }}
    >
      {/* Header row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 8px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <span style={{ color: statusColor, fontWeight: 700, fontSize: 13 }}>
          {statusLabel}
        </span>
        <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{toolCall.tool_name}</span>
        {toolCall.execution_time_ms != null && (
          <span style={{ opacity: 0.5, marginLeft: 'auto' }}>
            {toolCall.execution_time_ms}ms
          </span>
        )}
        <span style={{ opacity: 0.5 }}>{expanded ? '▲' : '▼'}</span>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div style={{ padding: '6px 10px', borderTop: '1px solid var(--color-border)' }}>
          <div style={{ opacity: 0.6, marginBottom: 2 }}>Arguments:</div>
          <pre
            style={{
              margin: 0,
              fontFamily: 'monospace',
              fontSize: 11,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {JSON.stringify(toolCall.arguments, null, 2)}
          </pre>

          {toolCall.result !== undefined && toolCall.result !== null && (
            <>
              <div style={{ opacity: 0.6, marginTop: 6, marginBottom: 2 }}>Result:</div>
              <pre
                style={{
                  margin: 0,
                  fontFamily: 'monospace',
                  fontSize: 11,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {typeof toolCall.result === 'string'
                  ? toolCall.result
                  : JSON.stringify(toolCall.result, null, 2)}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
