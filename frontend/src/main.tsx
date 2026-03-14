import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { applyTheme } from './lib/theme';
import type { Theme } from './types';

// Import WS store so that side-effects (wiring up wsClient) run at startup
import './stores/wsStore';
import './stores/chatStore';

// Apply theme from localStorage immediately (backup for cases where inline script missed)
const storedTheme = (localStorage.getItem('tequila.theme') as Theme) ?? 'system';
applyTheme(storedTheme);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
