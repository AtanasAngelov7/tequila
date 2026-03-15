/**
 * SessionSearch — debounced search bar + filter/sort controls for the session
 * sidebar (§9.5 filter controls).
 *
 * Filter state lives in the Zustand uiStore (ephemeral, not persisted) and
 * is passed to chatStore.loadSessions() whenever any value changes.
 */
import { useEffect, useRef } from 'react';
import { useUiStore } from '../../stores/uiStore';
import { useChatStore } from '../../stores/chatStore';

const DEBOUNCE_MS = 300;

export default function SessionSearch() {
  const {
    sessionSearch,
    sessionStatus,
    sessionKind,
    sessionSort,
    sessionOrder,
    setSessionSearch,
    setSessionStatus,
    setSessionKind,
    setSessionSort,
    setSessionOrder,
    clearSessionFilters,
  } = useUiStore();

  const { loadSessions } = useChatStore();

  // Debounce timer ref
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearch = (value: string) => {
    setSessionSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      loadSessions({
        q: value || undefined,
        status: sessionStatus || undefined,
        kind: sessionKind || undefined,
        sort: sessionSort,
        order: sessionOrder,
      });
    }, DEBOUNCE_MS);
  };

  const handleFilterChange = (
    field: 'status' | 'kind' | 'sort' | 'order',
    value: string,
  ) => {
    if (field === 'status') setSessionStatus(value);
    else if (field === 'kind') setSessionKind(value);
    else if (field === 'sort') setSessionSort(value);
    else setSessionOrder(value);

    // Reload immediately (no debounce for non-text changes)
    const next = {
      q: sessionSearch || undefined,
      status: field === 'status' ? value || undefined : sessionStatus || undefined,
      kind: field === 'kind' ? value || undefined : sessionKind || undefined,
      sort: field === 'sort' ? value : sessionSort,
      order: field === 'order' ? value : sessionOrder,
    };
    loadSessions(next);
  };

  const handleClear = () => {
    clearSessionFilters();
    loadSessions({ status: 'active', sort: 'last_activity', order: 'desc' });
  };

  // Cleanup debounce on unmount
  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current); }, []);

  const hasFilters = sessionSearch || sessionKind || sessionStatus !== 'active'
    || sessionSort !== 'last_activity' || sessionOrder !== 'desc';

  return (
    <div style={{ padding: '8px 12px 0', borderBottom: '1px solid var(--color-border)' }}>
      {/* Search input */}
      <div style={{ position: 'relative', marginBottom: 6 }}>
        <span
          style={{
            position: 'absolute',
            left: 8,
            top: '50%',
            transform: 'translateY(-50%)',
            opacity: 0.45,
            fontSize: 13,
            pointerEvents: 'none',
          }}
        >
          🔍
        </span>
        <input
          type="search"
          value={sessionSearch}
          onChange={(e) => handleSearch(e.target.value)}
          placeholder="Search sessions…"
          aria-label="Search sessions"
          style={{
            width: '100%',
            padding: '5px 28px 5px 28px',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            fontSize: 12,
            color: 'var(--color-on-surface)',
            boxSizing: 'border-box',
            outline: 'none',
          }}
        />
        {sessionSearch && (
          <button
            onClick={() => handleSearch('')}
            aria-label="Clear search"
            style={{
              position: 'absolute',
              right: 6,
              top: '50%',
              transform: 'translateY(-50%)',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: 12,
              opacity: 0.6,
              color: 'var(--color-on-surface)',
              padding: 0,
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        )}
      </div>

      {/* Filter row */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', paddingBottom: 6 }}>
        <select
          value={sessionStatus}
          onChange={(e) => handleFilterChange('status', e.target.value)}
          aria-label="Filter by status"
          style={selectStyle}
        >
          <option value="active">Active</option>
          <option value="idle">Idle</option>
          <option value="archived">Archived</option>
          <option value="">All</option>
        </select>

        <select
          value={sessionKind}
          onChange={(e) => handleFilterChange('kind', e.target.value)}
          aria-label="Filter by kind"
          style={selectStyle}
        >
          <option value="">All kinds</option>
          <option value="user">User</option>
          <option value="channel">Channel</option>
          <option value="cron">Cron</option>
          <option value="webhook">Webhook</option>
          <option value="agent">Agent</option>
        </select>

        <select
          value={sessionSort}
          onChange={(e) => handleFilterChange('sort', e.target.value)}
          aria-label="Sort sessions"
          style={selectStyle}
        >
          <option value="last_activity">Last activity</option>
          <option value="created">Created</option>
          <option value="message_count">Message count</option>
          <option value="title">Title A–Z</option>
        </select>

        <select
          value={sessionOrder}
          onChange={(e) => handleFilterChange('order', e.target.value)}
          aria-label="Sort direction"
          style={selectStyle}
        >
          <option value="desc">↓ Desc</option>
          <option value="asc">↑ Asc</option>
        </select>

        {hasFilters && (
          <button
            onClick={handleClear}
            title="Reset filters"
            style={{
              ...selectStyle,
              cursor: 'pointer',
              color: 'var(--color-primary)',
              fontWeight: 500,
            }}
          >
            Reset
          </button>
        )}
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  flex: '1 1 auto',
  minWidth: 0,
  padding: '3px 6px',
  fontSize: 11,
  backgroundColor: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 5,
  color: 'var(--color-on-surface)',
  cursor: 'pointer',
};
