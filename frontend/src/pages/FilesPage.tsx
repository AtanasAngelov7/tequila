/**
 * FilesPage — Storage dashboard: usage stats, orphan count, cleanup trigger (Sprint 15 D3).
 * Route: /files
 */
import React, { useEffect, useState, useCallback } from 'react';
import { filesApi, type FileStats } from '../api/files-api';

export default function FilesPage() {
  const [stats, setStats] = useState<FileStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStats(await filesApi.getStats());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const runCleanup = async () => {
    setCleaning(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const result = await filesApi.triggerCleanup();
      setSuccessMsg(
        `Cleanup complete. Now: ${result.total_files} files, ${result.total_size_mb.toFixed(1)} MB, ${result.orphaned_files} orphans.`
      );
      setStats(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setCleaning(false);
    }
  };

  const usedPct = stats && stats.quota_mb > 0
    ? Math.min(100, Math.round(stats.usage_percent))
    : null;

  const warnPct = 80;
  const isWarning = usedPct !== null && usedPct >= warnPct;

  return (
    <div style={pageStyle}>
      <div style={headerStyle}>
        <h2 style={{ margin: 0, fontSize: 20 }}>📁 File Storage</h2>
        <button
          onClick={runCleanup}
          disabled={cleaning || loading}
          style={btnPrimary}
        >
          {cleaning ? 'Running cleanup…' : '🧹 Run Cleanup'}
        </button>
      </div>

      {error && <div style={errorBanner}>{error}</div>}
      {successMsg && <div style={successBanner}>{successMsg}</div>}

      {loading && !stats && <p style={{ color: 'var(--color-muted)' }}>Loading…</p>}

      {stats && (
        <>
          {/* Summary cards */}
          <div style={cardRow}>
            <StatCard label="Total Files" value={String(stats.total_files)} />
            <StatCard label="Total Size" value={`${stats.total_size_mb.toFixed(1)} MB`} />
            <StatCard label="Pinned" value={String(stats.pinned_files)} />
            <StatCard
              label="Orphans"
              value={String(stats.orphaned_files)}
              highlight={stats.orphaned_files > 0}
            />
            <StatCard
              label="Orphan Size"
              value={`${stats.orphaned_size_mb.toFixed(1)} MB`}
              highlight={stats.orphaned_files > 0}
            />
          </div>

          {/* Quota bar */}
          {stats.quota_mb > 0 ? (
            <div style={quotaSection}>
              <div style={quotaHeader}>
                <span>Storage Quota</span>
                <span style={{ color: isWarning ? '#f59e0b' : 'inherit' }}>
                  {stats.total_size_mb.toFixed(1)} MB / {stats.quota_mb} MB
                  {usedPct !== null && ` (${usedPct}%)`}
                </span>
              </div>
              <div style={quotaBarTrack}>
                <div
                  style={{
                    ...quotaBarFill,
                    width: `${usedPct ?? 0}%`,
                    backgroundColor: isWarning ? '#f59e0b' : 'var(--color-primary, #6366f1)',
                  }}
                />
                <div
                  style={{ ...warnMarker, left: `${warnPct}%` }}
                  title={`Warning at ${warnPct}%`}
                />
              </div>
              {isWarning && (
                <p style={{ color: '#f59e0b', fontSize: 13, marginTop: 6 }}>
                  ⚠️ Storage usage above {warnPct}% warning threshold.
                </p>
              )}
            </div>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--color-muted)', marginBottom: 16 }}>
              No storage quota configured. Set <code>max_storage_mb</code> in storage settings to enable quota tracking.
            </p>
          )}

          {/* Orphan info */}
          <div style={sectionStyle}>
            <h3 style={sectionTitle}>
              Orphan Files
              <span style={badge}>{stats.orphaned_files}</span>
            </h3>
            {stats.orphaned_files === 0 ? (
              <p style={{ color: 'var(--color-muted)', fontSize: 13 }}>No orphan files detected. ✓</p>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--color-muted)' }}>
                {stats.orphaned_files} file{stats.orphaned_files !== 1 ? 's' : ''} ({stats.orphaned_size_mb.toFixed(1)} MB) are
                not referenced by any session and will be soft-deleted on the next cleanup run.
                Click <strong>Run Cleanup</strong> above to process them now.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ ...statCard, borderColor: highlight ? '#f59e0b' : 'var(--color-border)' }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: highlight ? '#f59e0b' : 'var(--color-on-surface)' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: 'var(--color-muted)', marginTop: 2 }}>{label}</div>
    </div>
  );
}

// --- styles ---

const pageStyle: React.CSSProperties = {
  padding: 24,
  overflowY: 'auto',
  height: '100%',
  boxSizing: 'border-box',
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  marginBottom: 20,
};

const btnPrimary: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 4,
  border: 'none',
  backgroundColor: 'var(--color-primary, #6366f1)',
  color: '#fff',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: 13,
};

const errorBanner: React.CSSProperties = {
  padding: '10px 14px',
  borderRadius: 4,
  backgroundColor: 'rgba(239,68,68,0.12)',
  color: '#ef4444',
  marginBottom: 12,
  fontSize: 13,
};

const successBanner: React.CSSProperties = {
  padding: '10px 14px',
  borderRadius: 4,
  backgroundColor: 'rgba(34,197,94,0.12)',
  color: '#22c55e',
  marginBottom: 12,
  fontSize: 13,
};

const cardRow: React.CSSProperties = {
  display: 'flex',
  gap: 12,
  flexWrap: 'wrap',
  marginBottom: 24,
};

const statCard: React.CSSProperties = {
  flex: '1 1 120px',
  minWidth: 100,
  padding: '14px 16px',
  borderRadius: 8,
  border: '1px solid var(--color-border)',
  backgroundColor: 'var(--color-surface)',
};

const quotaSection: React.CSSProperties = {
  marginBottom: 24,
  padding: '16px',
  borderRadius: 8,
  border: '1px solid var(--color-border)',
  backgroundColor: 'var(--color-surface)',
};

const quotaHeader: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  fontSize: 13,
  fontWeight: 600,
  marginBottom: 8,
};

const quotaBarTrack: React.CSSProperties = {
  position: 'relative',
  height: 8,
  borderRadius: 4,
  backgroundColor: 'var(--color-border)',
  overflow: 'visible',
};

const quotaBarFill: React.CSSProperties = {
  height: '100%',
  borderRadius: 4,
  transition: 'width 0.3s ease',
};

const warnMarker: React.CSSProperties = {
  position: 'absolute',
  top: -3,
  width: 2,
  height: 14,
  backgroundColor: '#f59e0b',
  borderRadius: 1,
};

const sectionStyle: React.CSSProperties = {
  marginBottom: 24,
};

const sectionTitle: React.CSSProperties = {
  fontSize: 15,
  fontWeight: 600,
  marginBottom: 12,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
};

const badge: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: 20,
  height: 20,
  borderRadius: 10,
  backgroundColor: 'var(--color-primary-muted, rgba(99,102,241,0.15))',
  color: 'var(--color-primary, #6366f1)',
  fontSize: 11,
  fontWeight: 700,
  padding: '0 6px',
};


