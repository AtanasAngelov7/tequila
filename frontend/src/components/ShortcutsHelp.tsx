import { useUiStore } from '../stores/uiStore';

const SHORTCUTS = [
  { keys: 'Ctrl+N', description: 'New session' },
  { keys: 'Ctrl+/', description: 'Toggle sidebar' },
  { keys: 'Ctrl+K', description: 'Command palette (stub)' },
  { keys: 'Ctrl+,', description: 'Open settings (stub)' },
  { keys: 'Ctrl+Shift+?', description: 'Show this help overlay' },
  { keys: 'Escape', description: 'Close modal / overlay' },
  { keys: 'Enter', description: 'Send message' },
  { keys: 'Shift+Enter', description: 'New line in message input' },
];

export default function ShortcutsHelp() {
  const { shortcutsHelpOpen, closeShortcutsHelp } = useUiStore();

  if (!shortcutsHelpOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      onClick={closeShortcutsHelp}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 12,
          padding: '24px 28px',
          minWidth: 380,
          maxWidth: 480,
          boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 16,
          }}
        >
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Keyboard Shortcuts</h2>
          <button
            onClick={closeShortcutsHelp}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: 18,
              color: 'var(--color-on-surface)',
              padding: 4,
            }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <tbody>
            {SHORTCUTS.map(({ keys, description }) => (
              <tr key={keys}>
                <td style={{ padding: '6px 0', paddingRight: 24, whiteSpace: 'nowrap' }}>
                  <kbd
                    style={{
                      backgroundColor: 'var(--color-sidebar)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4,
                      padding: '2px 7px',
                      fontSize: 12,
                      fontFamily: 'monospace',
                    }}
                  >
                    {keys}
                  </kbd>
                </td>
                <td style={{ padding: '6px 0', opacity: 0.8 }}>{description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
