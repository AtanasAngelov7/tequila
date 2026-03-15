import { useChatStore } from '../../stores/chatStore';

/**
 * TurnProgress — a compact status bar shown while a turn is in progress.
 * Displays "Thinking…", "Calling tool X…", or "Responding…" based on turnPhase.
 */
export default function TurnProgress() {
  const { turnPhase, isStreaming, activeToolName } = useChatStore();

  if (!isStreaming || turnPhase === 'idle') return null;

  const label =
    turnPhase === 'thinking'
      ? 'Thinking…'
      : turnPhase === 'tool_calling'
        ? `Calling tool${activeToolName ? ` ${activeToolName}` : ''}…`
        : 'Responding…';

  return (
    <div
      style={{
        padding: '4px 16px',
        fontSize: 11,
        opacity: 0.6,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}
      aria-live="polite"
      aria-label={label}
    >
      <Spinner />
      {label}
    </div>
  );
}

function Spinner() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 10,
        height: 10,
        border: '2px solid currentColor',
        borderTopColor: 'transparent',
        borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
      }}
    />
  );
}

// Inject animation keyframes once
if (typeof document !== 'undefined') {
  const styleId = '__tq_spinner_style';
  if (!document.getElementById(styleId)) {
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
    document.head.appendChild(style);
  }
}
