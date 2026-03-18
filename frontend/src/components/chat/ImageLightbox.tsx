// ImageLightbox — full-resolution image overlay with zoom/pan/navigation (§9.2a)
import { useEffect, useRef, useState } from 'react';

interface ImageLightboxProps {
  images: Array<{ src: string; alt?: string }>;
  initialIndex?: number;
  onClose: () => void;
}

export default function ImageLightbox({ images, initialIndex = 0, onClose }: ImageLightboxProps) {
  const [idx, setIdx] = useState(initialIndex);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, ox: 0, oy: 0 });

  const current = images[idx];

  const prev = () => { setIdx((i) => Math.max(0, i - 1)); setScale(1); setOffset({ x: 0, y: 0 }); };
  const next = () => { setIdx((i) => Math.min(images.length - 1, i + 1)); setScale(1); setOffset({ x: 0, y: 0 }); };

  // Keyboard navigation
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') prev();
      if (e.key === 'ArrowRight') next();
      if (e.key === '+' || e.key === '=') setScale((s) => Math.min(s + 0.25, 5));
      if (e.key === '-') setScale((s) => Math.max(s - 0.25, 0.25));
      if (e.key === '0') { setScale(1); setOffset({ x: 0, y: 0 }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Wheel zoom
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.15 : -0.15;
    setScale((s) => Math.min(Math.max(s + delta, 0.25), 8));
  };

  // Drag pan
  const onMouseDown = (e: React.MouseEvent) => {
    if (scale <= 1) return;
    dragging.current = true;
    dragStart.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return;
    setOffset({
      x: dragStart.current.ox + (e.clientX - dragStart.current.x),
      y: dragStart.current.oy + (e.clientY - dragStart.current.y),
    });
  };
  const onMouseUp = () => { dragging.current = false; };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0,0,0,0.88)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        userSelect: 'none',
      }}
      onClick={onClose}
      onWheel={onWheel}
    >
      {/* Image container — stop propagation so clicks on image don't close */}
      <div
        style={{
          position: 'relative',
          cursor: scale > 1 ? 'grab' : 'default',
          transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          transition: dragging.current ? 'none' : 'transform 0.1s ease',
        }}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
      >
        <img
          src={current.src}
          alt={current.alt ?? ''}
          style={{ maxWidth: '90vw', maxHeight: '85vh', objectFit: 'contain', display: 'block' }}
          draggable={false}
        />
      </div>

      {/* Navigation arrows */}
      {images.length > 1 && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); prev(); }}
            disabled={idx === 0}
            style={navBtnStyle('left')}
            title="Previous (←)"
          >
            ◀
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); next(); }}
            disabled={idx === images.length - 1}
            style={navBtnStyle('right')}
            title="Next (→)"
          >
            ▶
          </button>
        </>
      )}

      {/* Top bar */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'linear-gradient(to bottom, rgba(0,0,0,0.6), transparent)',
          color: '#fff',
          fontSize: 13,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <span style={{ opacity: 0.8 }}>
          {current.alt ?? `Image ${idx + 1}`}
          {images.length > 1 && <> · {idx + 1} / {images.length}</>}
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => setScale((s) => Math.min(s + 0.25, 8))} style={ctrlBtnStyle} title="Zoom in (+)">＋</button>
          <span style={{ fontSize: 12, opacity: 0.7, minWidth: 40, textAlign: 'center' }}>{Math.round(scale * 100)}%</span>
          <button onClick={() => setScale((s) => Math.max(s - 0.25, 0.25))} style={ctrlBtnStyle} title="Zoom out (-)">－</button>
          <button onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }); }} style={ctrlBtnStyle} title="Reset zoom (0)">⊡</button>
          <button onClick={onClose} style={{ ...ctrlBtnStyle, marginLeft: 8 }} title="Close (Esc)">✕</button>
        </div>
      </div>
    </div>
  );
}

const navBtnStyle = (side: 'left' | 'right'): React.CSSProperties => ({
  position: 'fixed',
  top: '50%',
  [side]: 20,
  transform: 'translateY(-50%)',
  background: 'rgba(255,255,255,0.12)',
  border: 'none',
  color: '#fff',
  fontSize: 20,
  padding: '12px 10px',
  borderRadius: 6,
  cursor: 'pointer',
  zIndex: 1001,
});

const ctrlBtnStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.15)',
  border: 'none',
  color: '#fff',
  fontSize: 14,
  padding: '4px 8px',
  borderRadius: 4,
  cursor: 'pointer',
};
