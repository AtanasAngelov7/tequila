/**
 * UpdateBanner — shows an update notification when a new version is available.
 *
 * - Polls /api/update/status on mount, then every 60 seconds.
 * - Shows when status is "available" or "ready".
 * - Supports "Download", "Install Now", and "Dismiss" actions.
 */
import React, { useCallback, useEffect, useState } from 'react';

interface UpdateState {
  current_version: string;
  latest_version: string | null;
  status: 'idle' | 'available' | 'downloading' | 'ready' | 'error';
  download_progress: number;
  changelog: string | null;
  error: string | null;
}

const POLL_INTERVAL_MS = 60_000;

async function fetchStatus(): Promise<UpdateState | null> {
  try {
    const resp = await fetch('/api/update/status');
    if (!resp.ok) return null;
    return resp.json() as Promise<UpdateState>;
  } catch {
    return null;
  }
}

async function postAction(action: 'check' | 'download' | 'apply'): Promise<UpdateState | null> {
  try {
    const resp = await fetch(`/api/update/${action}`, { method: 'POST' });
    if (!resp.ok) return null;
    return resp.json() as Promise<UpdateState>;
  } catch {
    return null;
  }
}

export default function UpdateBanner() {
  const [state, setState] = useState<UpdateState | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const s = await fetchStatus();
    if (s) setState(s);
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // Poll more frequently during a download
  useEffect(() => {
    if (state?.status !== 'downloading') return;
    const id = setInterval(refresh, 2_000);
    return () => clearInterval(id);
  }, [state?.status, refresh]);

  const handleDownload = async () => {
    setLoading(true);
    const s = await postAction('download');
    if (s) setState(s);
    setLoading(false);
  };

  const handleApply = async () => {
    setLoading(true);
    await postAction('apply');
    // Process will exit — if we get here the API returned an error
    setLoading(false);
    await refresh();
  };

  if (
    dismissed ||
    !state ||
    !['available', 'downloading', 'ready'].includes(state.status)
  ) {
    return null;
  }

  const pct = Math.round(state.download_progress * 100);

  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        backgroundColor: 'var(--color-primary-muted, rgba(99,102,241,0.15))',
        borderBottom: '1px solid var(--color-primary, #6366f1)',
        fontSize: 13,
        flexShrink: 0,
      }}
    >
      {/* Icon */}
      <span style={{ fontSize: 16 }}>🚀</span>

      {/* Text */}
      <span style={{ flex: 1 }}>
        {state.status === 'available' && (
          <>
            <strong>Update available:</strong> Tequila {state.latest_version} is ready to
            download.{state.changelog ? ` — ${state.changelog.split('\n')[0]}` : ''}
          </>
        )}
        {state.status === 'downloading' && (
          <>
            <strong>Downloading…</strong> {pct}% — Tequila {state.latest_version}
          </>
        )}
        {state.status === 'ready' && (
          <>
            <strong>Ready to install:</strong> Tequila {state.latest_version} has been
            downloaded. Restart to apply.
          </>
        )}
      </span>

      {/* Progress bar during download */}
      {state.status === 'downloading' && (
        <div
          style={{
            width: 120,
            height: 6,
            borderRadius: 3,
            backgroundColor: 'var(--color-border)',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: '100%',
              backgroundColor: 'var(--color-primary, #6366f1)',
              transition: 'width 0.3s ease',
            }}
          />
        </div>
      )}

      {/* Actions */}
      {state.status === 'available' && (
        <button
          onClick={handleDownload}
          disabled={loading}
          style={actionBtnStyle}
          title="Download update"
        >
          {loading ? '…' : 'Download'}
        </button>
      )}
      {state.status === 'ready' && (
        <button
          onClick={handleApply}
          disabled={loading}
          style={{ ...actionBtnStyle, backgroundColor: 'var(--color-primary, #6366f1)', color: '#fff' }}
          title="Install update now"
        >
          {loading ? '…' : 'Install Now'}
        </button>
      )}

      {/* Dismiss */}
      <button
        onClick={() => setDismissed(true)}
        style={dismissBtnStyle}
        title="Dismiss"
        aria-label="Dismiss update banner"
      >
        ✕
      </button>
    </div>
  );
}

const actionBtnStyle: React.CSSProperties = {
  padding: '4px 12px',
  borderRadius: 4,
  border: '1px solid var(--color-primary, #6366f1)',
  backgroundColor: 'transparent',
  color: 'var(--color-primary, #6366f1)',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
  flexShrink: 0,
};

const dismissBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: 'var(--color-on-surface)',
  fontSize: 14,
  padding: 4,
  flexShrink: 0,
  opacity: 0.6,
};
