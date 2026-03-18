// FileCard — file attachment card with 6 quick actions (§21.6)
import { useState } from 'react';
import type { FileRecord } from '../../api/files-api';
import { filesApi, formatBytes, mimeCategory } from '../../api/files-api';

interface FileCardProps {
  file: FileRecord;
  /** Called after pin/unpin so parent can refresh. */
  onPinToggle?: (fileId: string, pinned: boolean) => void;
  /** Called when "View" is clicked — opens side panel. */
  onView?: (file: FileRecord) => void;
  compact?: boolean;
}

const ICON: Record<string, string> = {
  image: '🖼️',
  pdf: '📄',
  audio: '🎵',
  code: '📝',
  other: '📎',
};

export default function FileCard({ file, onPinToggle, onView, compact = false }: FileCardProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const cat = mimeCategory(file.mime_type);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); } catch { /* errors visible via OS */ } finally { setBusy(null); }
  };

  const actions: Array<{ key: string; label: string; icon: string; onClick: () => void }> = [
    {
      key: 'download',
      label: 'Download',
      icon: '⬇️',
      onClick: () => filesApi.download(file.file_id, file.filename),
    },
    {
      key: 'open',
      label: 'Open file',
      icon: '↗️',
      onClick: () => run('open', () => filesApi.openFile(file.file_id)),
    },
    {
      key: 'reveal',
      label: 'Reveal in Explorer',
      icon: '📂',
      onClick: () => run('reveal', () => filesApi.revealFile(file.file_id)),
    },
    {
      key: 'view',
      label: 'View',
      icon: '👁️',
      onClick: () => onView?.(file),
    },
    {
      key: 'copy',
      label: 'Copy path',
      icon: '📋',
      onClick: () => navigator.clipboard.writeText(file.file_path),
    },
    {
      key: 'pin',
      label: file.pinned ? 'Unpin' : 'Pin',
      icon: file.pinned ? '📌' : '📍',
      onClick: () =>
        run('pin', async () => {
          if (file.pinned) {
            await filesApi.unpin(file.file_id);
            onPinToggle?.(file.file_id, false);
          } else {
            await filesApi.pin(file.file_id);
            onPinToggle?.(file.file_id, true);
          }
        }),
    },
  ];

  if (compact) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 8px',
          borderRadius: 6,
          border: '1px solid var(--color-border)',
          background: 'var(--color-surface)',
          fontSize: 12,
          maxWidth: 300,
        }}
      >
        <span>{ICON[cat]}</span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {file.filename}
        </span>
        <span style={{ opacity: 0.5, flexShrink: 0 }}>{formatBytes(file.size_bytes)}</span>
        {file.pinned && <span title="Pinned">📌</span>}
        <OverflowMenu actions={actions} busy={busy} />
      </div>
    );
  }

  return (
    <div
      style={{
        padding: '10px 12px',
        borderRadius: 8,
        border: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
        maxWidth: 320,
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 24 }}>{ICON[cat]}</span>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 13,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {file.filename}
          </div>
          <div style={{ fontSize: 11, opacity: 0.55 }}>
            {formatBytes(file.size_bytes)} · {file.mime_type}
          </div>
        </div>
        {file.pinned && <span title="Pinned">📌</span>}
      </div>

      {/* Preview thumbnail for images */}
      {cat === 'image' && (
        <img
          src={filesApi.previewUrl(file.file_id)}
          alt={file.filename}
          style={{
            width: '100%',
            maxHeight: 140,
            objectFit: 'cover',
            borderRadius: 4,
            marginBottom: 8,
            cursor: 'pointer',
          }}
          onClick={() => onView?.(file)}
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
        />
      )}

      {/* Quick actions row */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {actions.map((a) => (
          <button
            key={a.key}
            title={a.label}
            onClick={a.onClick}
            disabled={busy === a.key}
            style={{
              padding: '3px 7px',
              fontSize: 11,
              cursor: busy === a.key ? 'default' : 'pointer',
              borderRadius: 4,
              border: '1px solid var(--color-border)',
              background: 'none',
              color: 'var(--color-on-surface)',
              opacity: busy === a.key ? 0.4 : 0.8,
            }}
          >
            {a.icon} {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Overflow menu ─────────────────────────────────────────────────────────────

function OverflowMenu({
  actions,
  busy,
}: {
  actions: Array<{ key: string; label: string; icon: string; onClick: () => void }>;
  busy: string | null;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: '0 2px' }}
        title="More actions"
      >
        ⋮
      </button>
      {open && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 9 }}
            onClick={() => setOpen(false)}
          />
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: '100%',
              zIndex: 10,
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 6,
              boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
              minWidth: 160,
              padding: '4px 0',
            }}
          >
            {actions.map((a) => (
              <button
                key={a.key}
                onClick={() => { a.onClick(); setOpen(false); }}
                disabled={busy === a.key}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '6px 12px',
                  fontSize: 12,
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-on-surface)',
                  opacity: busy === a.key ? 0.4 : 1,
                }}
              >
                {a.icon} {a.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
