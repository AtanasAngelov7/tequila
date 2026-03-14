import React from 'react';
import { useUiStore } from '../../stores/uiStore';
import SessionList from '../session/SessionList';
import ThemeToggle from '../ThemeToggle';
import ShortcutsHelp from '../ShortcutsHelp';
import ConnectionStatus from '../ConnectionStatus';

interface AppLayoutProps {
  children: React.ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const { sidebarOpen, toggleSidebar } = useUiStore();

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Sidebar */}
      {sidebarOpen && (
        <aside
          style={{
            width: 260,
            flexShrink: 0,
            backgroundColor: 'var(--color-sidebar)',
            borderRight: '1px solid var(--color-border)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Sidebar header */}
          <div
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexShrink: 0,
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 15 }}>Tequila</span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <ConnectionStatus />
              <ThemeToggle />
              <button
                title="Toggle sidebar (Ctrl+/)"
                onClick={toggleSidebar}
                style={iconBtnStyle}
                aria-label="Close sidebar"
              >
                ☰
              </button>
            </div>
          </div>
          {/* Session list fills remaining space */}
          <div style={{ flex: 1, overflow: 'auto' }}>
            <SessionList />
          </div>
        </aside>
      )}

      {/* Main panel */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Top bar when sidebar is closed */}
        {!sidebarOpen && (
          <div
            style={{
              padding: '8px 16px',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <button onClick={toggleSidebar} style={iconBtnStyle} title="Open sidebar (Ctrl+/)">
              ☰
            </button>
            <span style={{ fontWeight: 600 }}>Tequila</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 12, alignItems: 'center' }}>
              <ConnectionStatus />
              <ThemeToggle />
            </div>
          </div>
        )}
        {children}
      </main>

      {/* Shortcuts help overlay */}
      <ShortcutsHelp />
    </div>
  );
}

const iconBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  padding: 4,
  fontSize: 16,
  color: 'var(--color-on-surface)',
  borderRadius: 4,
};
