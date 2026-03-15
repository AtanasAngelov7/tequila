import { useUiStore } from '../stores/uiStore';
import { applyTheme } from '../lib/theme';
import type { Theme } from '../types';

const THEMES: { value: Theme; icon: string; label: string }[] = [
  { value: 'light', icon: '☀️', label: 'Light' },
  { value: 'dark', icon: '🌙', label: 'Dark' },
  { value: 'system', icon: '🖥️', label: 'System' },
];

export default function ThemeToggle() {
  const { theme, setTheme } = useUiStore();

  const cycle = () => {
    const idx = THEMES.findIndex((t) => t.value === theme);
    const next = THEMES[(idx + 1) % THEMES.length];
    setTheme(next.value);
    applyTheme(next.value);
  };

  const current = THEMES.find((t) => t.value === theme) ?? THEMES[2];

  return (
    <button
      onClick={cycle}
      title={`Theme: ${current.label} (click to cycle)`}
      style={{
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        fontSize: 16,
        padding: 4,
        borderRadius: 4,
        lineHeight: 1,
      }}
      aria-label={`Current theme: ${current.label}`}
    >
      {current.icon}
    </button>
  );
}
