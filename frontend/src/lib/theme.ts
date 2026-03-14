import type { Theme } from '../types';

/** Read stored theme, resolve 'system', apply data-theme attribute on <html>. */
export function applyTheme(theme: Theme): void {
  let resolved: 'light' | 'dark' = 'light';
  if (theme === 'system') {
    resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } else {
    resolved = theme;
  }
  document.documentElement.setAttribute('data-theme', resolved);
}

/** Watch system preference changes when theme is 'system'. Returns cleanup fn. */
export function watchSystemTheme(onChange: () => void): () => void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener('change', onChange);
  return () => mq.removeEventListener('change', onChange);
}
