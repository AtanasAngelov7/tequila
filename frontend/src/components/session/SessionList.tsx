import { useEffect, useState } from 'react';
import { useChatStore } from '../../stores/chatStore';
import { useUiStore } from '../../stores/uiStore';
import SessionSearch from './SessionSearch';

export default function SessionList() {
  const {
    sessions,
    activeSessionId,
    isLoadingSessions,
    loadSessions,
    createSession,
    setActiveSession,
    renameSession,
  } = useChatStore();

  const { sessionSearch, sessionStatus, sessionKind, sessionSort, sessionOrder } = useUiStore();

  // Track which session is being renamed inline
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  // Load with current filters on mount
  useEffect(() => {
    loadSessions({
      q: sessionSearch || undefined,
      status: sessionStatus || undefined,
      kind: sessionKind || undefined,
      sort: sessionSort,
      order: sessionOrder,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNew = async () => {
    const session = await createSession();
    await setActiveSession(session.session_id);
  };

  const startRename = (sessionId: string, currentTitle: string | null) => {
    setRenamingId(sessionId);
    setRenameValue(currentTitle ?? '');
  };

  const commitRename = async (sessionId: string) => {
    if (renameValue.trim()) {
      await renameSession(sessionId, renameValue.trim());
    }
    setRenamingId(null);
    setRenameValue('');
  };

  const cancelRename = () => {
    setRenamingId(null);
    setRenameValue('');
  };

  return (
    <div style={{ padding: 0 }}>
      {/* Search + filter controls */}
      <SessionSearch />

      {/* New session button */}
      <div style={{ padding: '8px 12px 4px' }}>
        <button
          onClick={handleNew}
          title="New session (Ctrl+N)"
          style={{
            width: '100%',
            padding: '6px 12px',
            backgroundColor: 'var(--color-primary)',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          + New session
        </button>
      </div>

      {isLoadingSessions && (
        <div style={{ padding: '8px 16px', opacity: 0.6, fontSize: 12 }}>Loading…</div>
      )}

      {sessions.map((s) => (
        <div
          key={s.session_id}
          style={{
            display: 'block',
            width: '100%',
            background: s.session_id === activeSessionId ? 'var(--color-border)' : 'none',
            borderBottom: '1px solid transparent',
          }}
        >
          {renamingId === s.session_id ? (
            /* Inline rename input */
            <div style={{ padding: '6px 12px', display: 'flex', gap: 4 }}>
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(s.session_id);
                  if (e.key === 'Escape') cancelRename();
                }}
                onBlur={() => commitRename(s.session_id)}
                style={{
                  flex: 1,
                  fontSize: 12,
                  padding: '2px 6px',
                  border: '1px solid var(--color-primary)',
                  borderRadius: 4,
                  backgroundColor: 'var(--color-surface)',
                  color: 'var(--color-on-surface)',
                }}
              />
            </div>
          ) : (
            /* Normal session row */
            <button
              onClick={() => setActiveSession(s.session_id)}
              onDoubleClick={() => startRename(s.session_id, s.title)}
              title={`${s.title ?? 'Untitled'} — double-click to rename`}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 16px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                color: 'var(--color-on-surface)',
                borderRadius: 0,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {s.title ?? 'New Session'}
              </div>
              <div style={{ fontSize: 11, opacity: 0.55 }}>
                {s.message_count} msg · {s.status}
              </div>
            </button>
          )}
        </div>
      ))}

      {!isLoadingSessions && sessions.length === 0 && (
        <div style={{ padding: '8px 16px', opacity: 0.5, fontSize: 12 }}>
          No sessions found.
        </div>
      )}
    </div>
  );
}

