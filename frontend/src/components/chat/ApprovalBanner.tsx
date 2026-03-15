import { useEffect } from 'react';
import { useChatStore } from '../../stores/chatStore';

/**
 * ApprovalBanner — shown when a tool call requires user confirmation.
 * Keyboard shortcuts: Y = approve, N = deny, A = allow-all for this turn.
 */
export default function ApprovalBanner() {
  const { pendingApproval, approveToolCall, denyToolCall, allowAllTools } = useChatStore();

  // Keyboard shortcuts
  useEffect(() => {
    if (!pendingApproval) return;

    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const key = e.key.toLowerCase();
      if (key === 'y') approveToolCall(pendingApproval.tool_call_id);
      else if (key === 'n') denyToolCall(pendingApproval.tool_call_id);
      else if (key === 'a') allowAllTools();
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [pendingApproval, approveToolCall, denyToolCall, allowAllTools]);

  if (!pendingApproval) return null;

  return (
    <div
      role="alertdialog"
      aria-label="Tool approval required"
      style={{
        padding: '10px 16px',
        backgroundColor: 'var(--color-warning-bg, #fef3c7)',
        borderTop: '1px solid var(--color-warning-border, #f59e0b)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        fontSize: 13,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ flex: 1 }}>
        <strong>Approval required:</strong> tool{' '}
        <code
          style={{
            fontFamily: 'monospace',
            background: 'rgba(0,0,0,0.07)',
            padding: '1px 4px',
            borderRadius: 3,
          }}
        >
          {pendingApproval.tool_name}
        </code>{' '}
        wants to execute.
      </span>

      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={() => approveToolCall(pendingApproval.tool_call_id)}
          style={{
            padding: '4px 12px',
            borderRadius: 5,
            border: 'none',
            background: 'var(--color-success-btn, #22c55e)',
            color: '#fff',
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 600,
          }}
          title="Approve (Y)"
        >
          Approve <kbd>Y</kbd>
        </button>

        <button
          onClick={() => denyToolCall(pendingApproval.tool_call_id)}
          style={{
            padding: '4px 12px',
            borderRadius: 5,
            border: 'none',
            background: 'var(--color-danger-btn, #ef4444)',
            color: '#fff',
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 600,
          }}
          title="Deny (N)"
        >
          Deny <kbd>N</kbd>
        </button>

        <button
          onClick={allowAllTools}
          style={{
            padding: '4px 12px',
            borderRadius: 5,
            border: '1px solid var(--color-border)',
            background: 'transparent',
            cursor: 'pointer',
            fontSize: 12,
          }}
          title="Allow all tools for this turn (A)"
        >
          Allow-all <kbd>A</kbd>
        </button>
      </div>
    </div>
  );
}
