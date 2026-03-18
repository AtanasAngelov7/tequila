import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useUiStore } from '../../stores/uiStore';
import SessionList from '../session/SessionList';
import ThemeToggle from '../ThemeToggle';
import ShortcutsHelp from '../ShortcutsHelp';
import ConnectionStatus from '../ConnectionStatus';
import UpdateBanner from '../UpdateBanner';

interface AppLayoutProps {
  children: React.ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const { sidebarOpen, toggleSidebar } = useUiStore();
  const navigate = useNavigate();
  const location = useLocation();

  const navLinkStyle = (path: string): React.CSSProperties => ({
    display: 'block',
    padding: '8px 16px',
    fontSize: 13,
    cursor: 'pointer',
    backgroundColor: location.pathname === path ? 'var(--color-primary-muted, rgba(99,102,241,0.15))' : 'transparent',
    color: location.pathname === path ? 'var(--color-primary, #6366f1)' : 'var(--color-on-surface)',
    borderLeft: location.pathname === path ? '3px solid var(--color-primary, #6366f1)' : '3px solid transparent',
    textDecoration: 'none',
    fontWeight: location.pathname === path ? 600 : 400,
  });

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
          {/* Bottom navigation links */}
          <div style={{ borderTop: '1px solid var(--color-border)', flexShrink: 0 }}>
            <div style={navLinkStyle('/')} role="button" tabIndex={0} onClick={() => navigate('/')}>
              💬 Chat
            </div>
            <div style={navLinkStyle('/agents')} role="button" tabIndex={0} onClick={() => navigate('/agents')}>
              🤖 Agents
            </div>
            <div style={navLinkStyle('/diagnostics')} role="button" tabIndex={0} onClick={() => navigate('/diagnostics')}>
              🔍 Diagnostics
            </div>
            <div style={navLinkStyle('/plugins')} role="button" tabIndex={0} onClick={() => navigate('/plugins')}>
              🔌 Plugins
            </div>
            <div style={navLinkStyle('/auth')} role="button" tabIndex={0} onClick={() => navigate('/auth')}>
              🔑 Auth
            </div>
            <div style={navLinkStyle('/scheduler')} role="button" tabIndex={0} onClick={() => navigate('/scheduler')}>
              ⏰ Scheduler
            </div>
            <div style={navLinkStyle('/web-settings')} role="button" tabIndex={0} onClick={() => navigate('/web-settings')}>
              🌐 Web Settings
            </div>
            <div style={navLinkStyle('/skills')} role="button" tabIndex={0} onClick={() => navigate('/skills')}>
              🧩 Skills
            </div>
            <div style={navLinkStyle('/soul-editor')} role="button" tabIndex={0} onClick={() => navigate('/soul-editor')}>
              ✨ Soul Editor
            </div>
            <div style={navLinkStyle('/notifications')} role="button" tabIndex={0} onClick={() => navigate('/notifications')}>
              🔔 Notifications
            </div>
            <div style={navLinkStyle('/audit')} role="button" tabIndex={0} onClick={() => navigate('/audit')}>
              📋 Audit Log
            </div>
            <div style={navLinkStyle('/budget')} role="button" tabIndex={0} onClick={() => navigate('/budget')}>
              💰 Budget
            </div>
            <div style={navLinkStyle('/backup')} role="button" tabIndex={0} onClick={() => navigate('/backup')}>
              💾 Backup
            </div>
            <div style={navLinkStyle('/files')} role="button" tabIndex={0} onClick={() => navigate('/files')}>
              📁 Files
            </div>
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
        <UpdateBanner />
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
