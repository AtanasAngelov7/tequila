// MediaViewer — PDF and code/text side-panel viewer (§9.2a)
import { useEffect, useState } from 'react';
import { getAuthHeaders } from '../../api/client';

interface MediaViewerProps {
  type: 'pdf' | 'code';
  src: string;  // URL
  filename: string;
  onClose: () => void;
}

export default function MediaViewer({ type, src, filename, onClose }: MediaViewerProps) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(type === 'code');

  // Load text content for code files
  useEffect(() => {
    if (type !== 'code') return;
    setLoading(true);
    fetch(src, { headers: getAuthHeaders() })
      .then((r) => r.text())
      .then((t) => { setText(t); setLoading(false); })
      .catch(() => { setText('(Failed to load file content)'); setLoading(false); });
  }, [src, type]);

  // Esc to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: '40%',
        minWidth: 360,
        maxWidth: 720,
        zIndex: 900,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-border)',
        boxShadow: '-4px 0 20px rgba(0,0,0,0.18)',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 14px',
          borderBottom: '1px solid var(--color-border)',
          flexShrink: 0,
        }}
      >
        <span style={{ flex: 1, fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {type === 'pdf' ? '📄' : '📝'} {filename}
        </span>
        <a
          href={src}
          download={filename}
          style={{ fontSize: 12, opacity: 0.7, color: 'var(--color-on-surface)', textDecoration: 'none' }}
          title="Download"
        >
          ⬇️
        </a>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, opacity: 0.6, padding: '0 4px' }}
          title="Close (Esc)"
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        {type === 'pdf' && (
          <iframe
            src={src}
            style={{ width: '100%', height: '100%', border: 'none' }}
            title={filename}
          />
        )}
        {type === 'code' && (
          loading ? (
            <div style={{ padding: 16, opacity: 0.5, fontSize: 13 }}>Loading…</div>
          ) : (
            <pre
              style={{
                margin: 0,
                padding: 16,
                overflow: 'auto',
                height: '100%',
                fontSize: 12,
                lineHeight: 1.6,
                fontFamily: 'monospace',
                background: 'var(--color-surface)',
                color: 'var(--color-on-surface)',
                counterReset: 'line',
                whiteSpace: 'pre',
              }}
            >
              {text?.split('\n').map((line, i) => (
                <span key={i} style={{ display: 'block' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 36,
                      textAlign: 'right',
                      marginRight: 16,
                      opacity: 0.35,
                      userSelect: 'none',
                      fontSize: 11,
                    }}
                  >
                    {i + 1}
                  </span>
                  {line}
                </span>
              ))}
            </pre>
          )
        )}
      </div>
    </div>
  );
}
