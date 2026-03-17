import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import ChatPanel from './components/chat/ChatPanel';
import SetupWizard from './pages/SetupWizard';
import DiagnosticsPage from './pages/DiagnosticsPage';
import AgentsPage from './pages/AgentsPage';
import PluginsPage from './pages/PluginsPage';
import AuthSettingsPage from './pages/AuthSettingsPage';
import SchedulerPage from './pages/SchedulerPage';
import WebSettingsPage from './pages/WebSettingsPage';
import SkillManagerPage from './pages/SkillManagerPage';
import SoulEditorPage from './pages/SoulEditorPage';
import NotificationsPage from './pages/NotificationsPage';
import AuditLogPage from './pages/AuditLogPage';
import BudgetPage from './pages/BudgetPage';
import BackupPage from './pages/BackupPage';
import { wsClient } from './api/ws';
import { shortcutManager } from './lib/shortcuts';
import { applyTheme, watchSystemTheme } from './lib/theme';
import { useUiStore } from './stores/uiStore';
import { useChatStore } from './stores/chatStore';
import { api } from './api/client';

type AppMode = 'loading' | 'setup' | 'app' | 'error';

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
      <Route
        path="/agents"
        element={
          <AppLayout>
            <AgentsPage />
          </AppLayout>
        }
      />
      <Route
        path="/plugins"
        element={
          <AppLayout>
            <PluginsPage />
          </AppLayout>
        }
      />
      <Route
        path="/auth"
        element={
          <AppLayout>
            <AuthSettingsPage />
          </AppLayout>
        }
      />
      <Route
        path="/scheduler"
        element={
          <AppLayout>
            <SchedulerPage />
          </AppLayout>
        }
      />
      <Route
        path="/web-settings"
        element={
          <AppLayout>
            <WebSettingsPage />
          </AppLayout>
        }
      />
      <Route
        path="/skills"
        element={
          <AppLayout>
            <SkillManagerPage />
          </AppLayout>
        }
      />
      <Route
        path="/soul-editor"
        element={
          <AppLayout>
            <SoulEditorPage />
          </AppLayout>
        }
      />
      <Route
        path="/notifications"
        element={
          <AppLayout>
            <NotificationsPage />
          </AppLayout>
        }
      />
      <Route
        path="/audit"
        element={
          <AppLayout>
            <AuditLogPage />
          </AppLayout>
        }
      />
      <Route
        path="/budget"
        element={
          <AppLayout>
            <BudgetPage />
          </AppLayout>
        }
      />
      <Route
        path="/backup"
        element={
          <AppLayout>
            <BackupPage />
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
        // TD-253: Show connection error instead of broken app UI
        setMode('error');
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

  // TD-253: Show a connection error state with retry button
  if (mode === 'error') {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          gap: 12,
          color: 'var(--color-on-surface)',
          fontSize: 14,
        }}
      >
        <p style={{ opacity: 0.7 }}>Unable to connect to the Tequila server.</p>
        <button
          onClick={() => {
            setMode('loading');
            api
              .get<{ setup_complete: boolean }>('/setup/status')
              .then((data) => setMode(data.setup_complete ? 'app' : 'setup'))
              .catch(() => setMode('error'));
          }}
          style={{ padding: '6px 16px', cursor: 'pointer' }}
        >
          Retry
        </button>
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
