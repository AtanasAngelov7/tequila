// AudioPlayer — inline audio player widget (§9.2a)
import { useEffect, useRef, useState } from 'react';

interface AudioPlayerProps {
  src: string;
  filename: string;
}

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export default function AudioPlayer({ src, filename }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speedIdx, setSpeedIdx] = useState(2); // 1×

  const speed = SPEEDS[speedIdx];

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => setCurrentTime(el.currentTime);
    const onMeta = () => setDuration(el.duration);
    const onEnded = () => setPlaying(false);
    el.addEventListener('timeupdate', onTime);
    el.addEventListener('loadedmetadata', onMeta);
    el.addEventListener('ended', onEnded);
    return () => {
      el.removeEventListener('timeupdate', onTime);
      el.removeEventListener('loadedmetadata', onMeta);
      el.removeEventListener('ended', onEnded);
    };
  }, []);

  // Sync playback rate
  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [speed]);

  const togglePlay = () => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) { el.pause(); setPlaying(false); }
    else { el.play(); setPlaying(true); }
  };

  const seek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const t = Number(e.target.value);
    setCurrentTime(t);
    if (audioRef.current) audioRef.current.currentTime = t;
  };

  const cycleSpeed = () => setSpeedIdx((i) => (i + 1) % SPEEDS.length);

  const fmt = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 10px',
        borderRadius: 8,
        border: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
        maxWidth: 360,
        fontSize: 12,
      }}
    >
      <audio ref={audioRef} src={src} preload="metadata" />

      {/* Filename */}
      <span title={filename} style={{ opacity: 0.6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 80 }}>
        🎵 {filename}
      </span>

      {/* Play/pause */}
      <button
        onClick={togglePlay}
        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, padding: 0, lineHeight: 1 }}
        title={playing ? 'Pause' : 'Play'}
      >
        {playing ? '⏸' : '▶️'}
      </button>

      {/* Seek bar */}
      <input
        type="range"
        min={0}
        max={duration || 1}
        step={0.1}
        value={currentTime}
        onChange={seek}
        style={{ flex: 1, minWidth: 60 }}
        title="Seek"
      />

      {/* Time */}
      <span style={{ opacity: 0.7, whiteSpace: 'nowrap', minWidth: 60, textAlign: 'center' }}>
        {fmt(currentTime)} / {fmt(duration)}
      </span>

      {/* Speed selector */}
      <button
        onClick={cycleSpeed}
        style={{
          background: 'none',
          border: '1px solid var(--color-border)',
          cursor: 'pointer',
          fontSize: 11,
          padding: '2px 5px',
          borderRadius: 4,
          color: 'var(--color-on-surface)',
          whiteSpace: 'nowrap',
        }}
        title="Playback speed"
      >
        {speed}×
      </button>
    </div>
  );
}
