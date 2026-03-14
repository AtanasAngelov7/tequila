import React, { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import ChatPanel from './components/chat/ChatPanel';
import SetupWizard from './pages/SetupWizard';
import DiagnosticsPage from './pages/DiagnosticsPage';
import { wsClient } from './api/ws';
import { shortcutManager } from './lib/shortcuts';
import { applyTheme, watchSystemTheme } from './lib/theme';
import { useUiStore } from './stores/uiStore';
import { useChatStore } from './stores/chatStore';
import { api } from './api/client';

type AppMode = 'loading' | 'setup' | 'app';

function MainApp() {
  const { theme, toggleSidebar, toggleShortcutsHelp, closeShortcutsHelp } = useUiStore();
  const { createSession, setActiveSession } = useChatStore();

  // Apply theme reactively
  useEffect(() => {
    applyTheme(theme);
    const cleanup = watchSystemTheme(() => applyTheme(theme));
    return cleanup;
  }, [theme]);

  // Start WebSocket on mount
  useEffect(() => {
    wsClient.connect();
    return () => wsClient.destroy();
  }, []);

  // Register global keyboard shortcuts
  useEffect(() => {
    shortcutManager.mount();

    const unreg = [
      shortcutManager.register({
        key: 'n',
        ctrl: true,
        description: 'New session',
        handler: async () => {
          const session = await createSession();
          await setActiveSession(session.session_id);
        },
      }),
      shortcutManager.register({
        key: '/',
        ctrl: true,
        description: 'Toggle sidebar',
        handler: toggleSidebar,
      }),
      shortcutManager.register({
        key: '?',
        ctrl: true,
        shift: true,
        description: 'Show shortcuts help',
        handler: toggleShortcutsHelp,
      }),
      shortcutManager.register({
        key: 'Escape',
        description: 'Close modal',
        handler: closeShortcutsHelp,
      }),
      shortcutManager.register({
        key: 'k',
        ctrl: true,
        description: 'Command palette (stub)',
        handler: () => {
          // TODO: Sprint 05+ will implement full command palette
          console.info('Command palette — coming soon');
        },
      }),
    ];

    return () => {
      shortcutManager.unmount();
      unreg.forEach((fn) => fn());
    };
  }, [toggleSidebar, toggleShortcutsHelp, closeShortcutsHelp, createSession, setActiveSession]);

  return (
    <Routes>
      <Route
        path="/"
        element={
          <AppLayout>
            <ChatPanel />
          </AppLayout>
        }
      />
      <Route
        path="/diagnostics"
        element={
          <AppLayout>
            <DiagnosticsPage />
          </AppLayout>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  const [mode, setMode] = useState<AppMode>('loading');

  // On mount, check whether setup has been completed.
  useEffect(() => {
    api
      .get<{ setup_complete: boolean }>('/setup/status')
      .then((data) => {
        setMode(data.setup_complete ? 'app' : 'setup');
      })
      .catch(() => {
        // If the setup status check fails (e.g. server not up yet), show app.
        setMode('app');
      });
  }, []);

  if (mode === 'loading') {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          color: 'var(--color-on-surface)',
          opacity: 0.5,
          fontSize: 14,
        }}
      >
        Loading…
      </div>
    );
  }

  if (mode === 'setup') {
    return <SetupWizard onComplete={() => setMode('app')} />;
  }

  return (
    <BrowserRouter>
      <MainApp />
    </BrowserRouter>
  );
}
