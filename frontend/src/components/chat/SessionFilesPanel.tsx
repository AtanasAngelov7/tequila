// SessionFilesPanel — right-sidebar file browser (§9.2b)
// Toggle: 📎 button or Ctrl+Shift+F
import { useEffect, useMemo, useState } from 'react';
import { useChatStore } from '../../stores/chatStore';
import { filesApi, formatBytes, mimeCategory } from '../../api/files-api';
import type { FileRecord } from '../../api/files-api';

type SortKey = 'date' | 'name' | 'size';
type MimeCat = 'all' | 'images' | 'documents' | 'audio' | 'other';

interface SessionFilesPanelProps {
  onClose: () => void;
}

export default function SessionFilesPanel({ onClose }: SessionFilesPanelProps) {
  const { activeSessionId } = useChatStore();
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState<MimeCat>('all');
  const [sortBy, setSortBy] = useState<SortKey>('date');

  // Esc to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (!activeSessionId) return;
    setLoading(true);
    filesApi
      .listSessionFiles(activeSessionId)
      .then(setFiles)
      .catch(() => setFiles([]))
      .finally(() => setLoading(false));
  }, [activeSessionId]);

  const handlePinToggle = (fileId: string, pinned: boolean) => {
    setFiles((prev) => prev.map((f) => (f.file_id === fileId ? { ...f, pinned } : f)));
  };

  const catMatches = (f: FileRecord): boolean => {
    if (catFilter === 'all') return true;
    const cat = mimeCategory(f.mime_type);
    if (catFilter === 'images') return cat === 'image';
    if (catFilter === 'documents') return cat === 'pdf' || cat === 'code' || cat === 'other';
    if (catFilter === 'audio') return cat === 'audio';
    if (catFilter === 'other') return cat === 'other';
    return true;
  };

  const filtered = useMemo(() => {
    let result = files.filter((f) => !f.deleted);
    if (search) result = result.filter((f) => f.filename.toLowerCase().includes(search.toLowerCase()));
    result = result.filter(catMatches);
    if (sortBy === 'name') result = [...result].sort((a, b) => a.filename.localeCompare(b.filename));
    else if (sortBy === 'size') result = [...result].sort((a, b) => b.size_bytes - a.size_bytes);
    else result = [...result].sort((a, b) => b.created_at.localeCompare(a.created_at));
    return result;
  }, [files, search, catFilter, sortBy]);

  const uploads = filtered.filter((f) => f.origin === 'upload');
  const generated = filtered.filter((f) => f.origin === 'agent_generated');

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: 320,
        zIndex: 800,
        background: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-border)',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '-4px 0 16px rgba(0,0,0,0.12)',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '10px 14px',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>📎 Session Files</span>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, opacity: 0.6 }}
          title="Close (Esc)"
        >
          ✕
        </button>
      </div>

      {/* Filters */}
      <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>
        <input
          type="text"
          placeholder="Search files…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: '100%',
            padding: '5px 8px',
            fontSize: 12,
            borderRadius: 4,
            border: '1px solid var(--color-border)',
            background: 'var(--color-background)',
            color: 'var(--color-on-surface)',
            marginBottom: 6,
            boxSizing: 'border-box',
          }}
        />
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {(['all', 'images', 'documents', 'audio', 'other'] as MimeCat[]).map((c) => (
            <button
              key={c}
              onClick={() => setCatFilter(c)}
              style={{
                fontSize: 11,
                padding: '2px 7px',
                borderRadius: 4,
                border: '1px solid var(--color-border)',
                background: catFilter === c ? 'var(--color-primary, #6366f1)' : 'none',
                color: catFilter === c ? '#fff' : 'var(--color-on-surface)',
                cursor: 'pointer',
              }}
            >
              {c.charAt(0).toUpperCase() + c.slice(1)}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortKey)}
            style={{ fontSize: 11, padding: '2px 4px', borderRadius: 4, border: '1px solid var(--color-border)', background: 'var(--color-surface)', color: 'var(--color-on-surface)' }}
          >
            <option value="date">Date</option>
            <option value="name">Name</option>
            <option value="size">Size</option>
          </select>
        </div>
      </div>

      {/* File list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 14px' }}>
        {loading && <p style={{ opacity: 0.5, fontSize: 12 }}>Loading…</p>}
        {!loading && filtered.length === 0 && (
          <p style={{ opacity: 0.45, fontSize: 12, textAlign: 'center', marginTop: 24 }}>No files</p>
        )}

        {uploads.length > 0 && (
          <FileGroup label="Uploads" files={uploads} onPinToggle={handlePinToggle} />
        )}
        {generated.length > 0 && (
          <FileGroup label="Agent Generated" files={generated} onPinToggle={handlePinToggle} />
        )}
      </div>
    </div>
  );
}

// ── File group ────────────────────────────────────────────────────────────────

function FileGroup({
  label,
  files,
  onPinToggle,
}: {
  label: string;
  files: FileRecord[];
  onPinToggle: (id: string, pinned: boolean) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div style={{ marginBottom: 12 }}>
      <button
        onClick={() => setCollapsed((v) => !v)}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: 12,
          fontWeight: 600,
          opacity: 0.65,
          padding: '4px 0',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          color: 'var(--color-on-surface)',
        }}
      >
        {collapsed ? '▶' : '▼'} {label} ({files.length})
      </button>

      {!collapsed && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
          {files.map((f) => (
            <div key={f.file_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <div style={{ fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.pinned && <span title="Pinned">📌 </span>}{f.filename}
                </div>
                <div style={{ fontSize: 11, opacity: 0.5 }}>{formatBytes(f.size_bytes)} · {f.created_at.slice(0, 10)}</div>
              </div>
              <RowActions file={f} onPinToggle={onPinToggle} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Row actions ───────────────────────────────────────────────────────────────

function RowActions({ file, onPinToggle }: { file: FileRecord; onPinToggle: (id: string, pinned: boolean) => void }) {
  const [open, setOpen] = useState(false);

  const actions = [
    { label: '⬇️ Download', fn: () => filesApi.download(file.file_id, file.filename) },
    { label: '↗️ Open file', fn: () => filesApi.openFile(file.file_id) },
    { label: '📂 Reveal in Explorer', fn: () => filesApi.revealFile(file.file_id) },
    { label: '📋 Copy path', fn: () => navigator.clipboard.writeText(file.file_path) },
    {
      label: file.pinned ? '📍 Unpin' : '📌 Pin',
      fn: async () => {
        if (file.pinned) { await filesApi.unpin(file.file_id); onPinToggle(file.file_id, false); }
        else { await filesApi.pin(file.file_id); onPinToggle(file.file_id, true); }
      },
    },
  ];

  return (
    <div style={{ position: 'relative', flexShrink: 0 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: '2px 4px', opacity: 0.6 }}
        title="Actions"
      >
        ⋮
      </button>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 9 }} onClick={() => setOpen(false)} />
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
              minWidth: 180,
              padding: '4px 0',
            }}
          >
            {actions.map((a) => (
              <button
                key={a.label}
                onClick={() => { a.fn(); setOpen(false); }}
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
                }}
              >
                {a.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
