import { useState } from 'react';
import { useChatStore } from '../../stores/chatStore';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import TurnProgress from './TurnProgress';
import ApprovalBanner from './ApprovalBanner';

function ExportMenu({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const doExport = async (format: 'markdown' | 'json' | 'pdf') => {
    setOpen(false);
    setExporting(true);
    try {
      const token = (import.meta as any).env?.VITE_GATEWAY_TOKEN ?? '';
      const url = `/api/sessions/${sessionId}/export?format=${format}&include_costs=true`;
      const res = await fetch(url, {
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const ext = format === 'json' ? 'json' : format === 'pdf' ? 'pdf' : 'md';
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = `session_${sessionId.slice(0, 8)}.${ext}`;
      a.click();
      URL.revokeObjectURL(objectUrl);
    } catch (e) {
      alert(`Export error: ${e}`);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={exporting}
        title="Export session transcript"
        style={{
          padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-border)',
          background: 'var(--color-surface)', color: 'var(--color-on-surface)',
          cursor: 'pointer', fontSize: 12,
        }}
      >
        {exporting ? '…' : '⬇ Export'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', right: 0, top: '110%', zIndex: 100,
          background: 'var(--color-surface)', border: '1px solid var(--color-border)',
          borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.15)', minWidth: 140,
        }}>
          {(['markdown', 'json', 'pdf'] as const).map((fmt) => (
            <button
              key={fmt}
              onClick={() => doExport(fmt)}
              style={{
                display: 'block', width: '100%', padding: '8px 14px', textAlign: 'left',
                border: 'none', background: 'none', cursor: 'pointer', fontSize: 13,
                color: 'var(--color-on-surface)',
              }}
            >
              {fmt.toUpperCase()}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChatPanel() {
  const { activeSessionId, sendMessage } = useChatStore();

  if (!activeSessionId) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: 0.45,
          fontSize: 14,
        }}
      >
        Select or create a session to start chatting.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Session header toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
        padding: '4px 12px', borderBottom: '1px solid var(--color-border)',
        gap: 8, flexShrink: 0,
      }}>
        <ExportMenu sessionId={activeSessionId} />
      </div>
      <MessageList />
      <TurnProgress />
      <ApprovalBanner />
      <MessageInput onSend={sendMessage} />
    </div>
  );
}
