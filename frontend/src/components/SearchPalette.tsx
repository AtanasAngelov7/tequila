/**
 * SearchPalette — Global Cmd+K command/search overlay (Sprint 15 D2 §9.2).
 * Searches sessions, settings pages, and agent names.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useChatStore } from '../stores/chatStore';
import type { Session } from '../types';

interface SearchResult {
  id: string;
  icon: string;
  title: string;
  subtitle?: string;
  action: () => void;
}

const STATIC_ITEMS: Omit<SearchResult, 'action'>[] = [
  { id: 'nav-chat',          icon: '💬', title: 'Chat',              subtitle: 'Main chat panel' },
  { id: 'nav-agents',        icon: '🤖', title: 'Agents',            subtitle: 'Agent management' },
  { id: 'nav-plugins',       icon: '🔌', title: 'Plugins',           subtitle: 'Plugin management' },
  { id: 'nav-skills',        icon: '🧩', title: 'Skills',            subtitle: 'Skill library' },
  { id: 'nav-soul-editor',   icon: '✨', title: 'Soul Editor',       subtitle: 'Agent personality' },
  { id: 'nav-scheduler',     icon: '⏰', title: 'Scheduler',         subtitle: 'Scheduled tasks' },
  { id: 'nav-web-settings',  icon: '🌐', title: 'Web Settings',      subtitle: 'Browser & vision' },
  { id: 'nav-notifications', icon: '🔔', title: 'Notifications',     subtitle: 'Notification preferences' },
  { id: 'nav-audit',         icon: '📋', title: 'Audit Log',         subtitle: 'System audit events' },
  { id: 'nav-budget',        icon: '💰', title: 'Budget',            subtitle: 'LLM cost tracking' },
  { id: 'nav-backup',        icon: '💾', title: 'Backup',            subtitle: 'Create and restore backups' },
  { id: 'nav-files',         icon: '📁', title: 'Files',             subtitle: 'File storage dashboard' },
  { id: 'nav-auth',          icon: '🔑', title: 'Auth Settings',     subtitle: 'Authentication settings' },
  { id: 'nav-diagnostics',   icon: '🔍', title: 'Diagnostics',       subtitle: 'System diagnostics' },
];

const NAV_ROUTES: Record<string, string> = {
  'nav-chat':          '/',
  'nav-agents':        '/agents',
  'nav-plugins':       '/plugins',
  'nav-skills':        '/skills',
  'nav-soul-editor':   '/soul-editor',
  'nav-scheduler':     '/scheduler',
  'nav-web-settings':  '/web-settings',
  'nav-notifications': '/notifications',
  'nav-audit':         '/audit',
  'nav-budget':        '/budget',
  'nav-backup':        '/backup',
  'nav-files':         '/files',
  'nav-auth':          '/auth',
  'nav-diagnostics':   '/diagnostics',
};

interface SearchPaletteProps {
  open: boolean;
  onClose: () => void;
}

export default function SearchPalette({ open, onClose }: SearchPaletteProps) {
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { sessions } = useChatStore();

  // Build full result list
  const buildResults = useCallback((): SearchResult[] => {
    const q = query.toLowerCase();

    // Static nav items
    const navResults: SearchResult[] = STATIC_ITEMS
      .filter((it) => !q || it.title.toLowerCase().includes(q) || (it.subtitle ?? '').toLowerCase().includes(q))
      .map((it) => ({
        ...it,
        action: () => {
          navigate(NAV_ROUTES[it.id] ?? '/');
          onClose();
        },
      }));

    // Session results (only when query given, otherwise skip for brevity)
    const sessionResults: SearchResult[] = q
      ? sessions
          .filter(
            (s: Session) =>
              s.title?.toLowerCase().includes(q) ||
              s.session_id.toLowerCase().includes(q)
          )
          .slice(0, 8)
          .map((s: Session) => ({
            id: `session-${s.session_id}`,
            icon: '💬',
            title: s.title ?? 'Untitled session',
            subtitle: `Session · ${s.session_id.slice(0, 8)}`,
            action: () => {
              navigate('/');
              // Switch to session — handled by chatStore side-effect
              useChatStore.getState().setActiveSession(s.session_id);
              onClose();
            },
          }))
      : [];

    return [...navResults, ...sessionResults];
  }, [query, sessions, navigate, onClose]);

  const results = buildResults();

  // Auto-scroll active item into view
  useEffect(() => {
    if (!listRef.current) return;
    const item = listRef.current.querySelector(`[data-idx="${activeIdx}"]`) as HTMLElement | null;
    item?.scrollIntoView({ block: 'nearest' });
  }, [activeIdx]);

  // Reset on open
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIdx(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  // Keep activeIdx in bounds when results change
  useEffect(() => {
    setActiveIdx((prev) => Math.min(prev, Math.max(0, results.length - 1)));
  }, [results.length]);

  const confirm = useCallback(
    (idx: number) => {
      const r = results[idx];
      if (r) r.action();
    },
    [results]
  );

  if (!open) return null;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((p) => Math.min(p + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((p) => Math.max(p - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      confirm(activeIdx);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        style={backdropStyle}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      />
      {/* Palette panel */}
      <div style={paletteStyle} role="dialog" aria-label="Command palette">
        {/* Search input */}
        <div style={inputWrapper}>
          <span style={searchIcon}>🔍</span>
          <input
            ref={inputRef}
            type="text"
            placeholder="Search pages, sessions, settings…"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
            onKeyDown={handleKeyDown}
            style={inputStyle}
            aria-label="Search"
          />
          {query && (
            <button
              style={clearBtn}
              onClick={() => { setQuery(''); inputRef.current?.focus(); }}
              title="Clear"
            >
              ×
            </button>
          )}
        </div>

        {/* Results list */}
        <div ref={listRef} style={listStyle} role="listbox">
          {results.length === 0 && (
            <div style={emptyState}>No results for "{query}"</div>
          )}
          {results.map((r, i) => (
            <div
              key={r.id}
              data-idx={i}
              role="option"
              aria-selected={i === activeIdx}
              style={{
                ...resultItem,
                backgroundColor: i === activeIdx
                  ? 'var(--color-primary-muted, rgba(99,102,241,0.1))'
                  : 'transparent',
              }}
              onMouseEnter={() => setActiveIdx(i)}
              onMouseDown={(e) => { e.preventDefault(); confirm(i); }}
            >
              <span style={resultIcon}>{r.icon}</span>
              <span style={resultBody}>
                <span style={resultTitle}>{highlight(r.title, query)}</span>
                {r.subtitle && (
                  <span style={resultSub}>{highlight(r.subtitle, query)}</span>
                )}
              </span>
              {i === activeIdx && <span style={returnHint}>↵</span>}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div style={footer}>
          <span>↑↓ navigate</span>
          <span>↵ select</span>
          <span>Esc close</span>
        </div>
      </div>
    </>
  );
}

/** Wrap matched substring in <mark>. */
function highlight(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark style={{ backgroundColor: 'rgba(99,102,241,0.25)', borderRadius: 2, padding: '0 1px' }}>
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const backdropStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0,0,0,0.45)',
  zIndex: 900,
};

const paletteStyle: React.CSSProperties = {
  position: 'fixed',
  top: '15%',
  left: '50%',
  transform: 'translateX(-50%)',
  width: '100%',
  maxWidth: 580,
  borderRadius: 12,
  backgroundColor: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 48px rgba(0,0,0,0.35)',
  zIndex: 901,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
};

const inputWrapper: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  padding: '10px 16px',
  borderBottom: '1px solid var(--color-border)',
  gap: 8,
};

const searchIcon: React.CSSProperties = {
  fontSize: 16,
  flexShrink: 0,
};

const inputStyle: React.CSSProperties = {
  flex: 1,
  background: 'none',
  border: 'none',
  outline: 'none',
  fontSize: 15,
  color: 'var(--color-on-surface)',
  caretColor: 'var(--color-primary, #6366f1)',
};

const clearBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: 'var(--color-muted)',
  fontSize: 18,
  padding: 0,
  lineHeight: 1,
};

const listStyle: React.CSSProperties = {
  maxHeight: 360,
  overflowY: 'auto',
  padding: '4px 0',
};

const resultItem: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '8px 16px',
  cursor: 'pointer',
  userSelect: 'none',
  transition: 'background 0.1s',
};

const resultIcon: React.CSSProperties = {
  fontSize: 16,
  flexShrink: 0,
  width: 22,
  textAlign: 'center',
};

const resultBody: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  minWidth: 0,
};

const resultTitle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 500,
  lineHeight: 1.3,
};

const resultSub: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--color-muted)',
  marginTop: 1,
};

const returnHint: React.CSSProperties = {
  fontSize: 11,
  color: 'var(--color-muted)',
  flexShrink: 0,
};

const emptyState: React.CSSProperties = {
  padding: '24px 16px',
  textAlign: 'center',
  color: 'var(--color-muted)',
  fontSize: 14,
};

const footer: React.CSSProperties = {
  display: 'flex',
  gap: 16,
  padding: '6px 16px',
  borderTop: '1px solid var(--color-border)',
  fontSize: 11,
  color: 'var(--color-muted)',
};
