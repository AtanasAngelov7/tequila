/**
 * NotificationsPage — view and manage notifications (Sprint 14b D1).
 * Route: /notifications
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface Notification {
  id: string;
  notification_type: string;
  title: string;
  body: string;
  severity: 'info' | 'warning' | 'error';
  action_url: string | null;
  read: boolean;
  created_at: string;
}

interface NotificationPreference {
  id: string | null;
  notification_type: string;
  channels: string[];
  enabled: boolean;
}

const severityColor: Record<string, string> = {
  info: 'var(--color-primary, #6366f1)',
  warning: '#f59e0b',
  error: '#ef4444',
};

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [preferences, setPreferences] = useState<NotificationPreference[]>([]);
  const [tab, setTab] = useState<'inbox' | 'preferences'>('inbox');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [notifs, prefs] = await Promise.all([
        api.get<Notification[]>(`/notifications?unread_only=${unreadOnly}`),
        api.get<NotificationPreference[]>('/notifications/preferences'),
      ]);
      setNotifications(notifs);
      setPreferences(prefs);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [unreadOnly]);

  useEffect(() => { load(); }, [load]);

  const markRead = async (id: string) => {
    try {
      await api.patch(`/notifications/${id}/read`, {});
      setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, read: true } : n));
    } catch (e) {
      setError(String(e));
    }
  };

  const markAllRead = async () => {
    try {
      await api.post('/notifications/read-all', {});
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    } catch (e) {
      setError(String(e));
    }
  };

  const togglePreference = async (pref: NotificationPreference) => {
    try {
      await api.put('/notifications/preferences', [{ ...pref, enabled: !pref.enabled }]);
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 16 }}>🔔 Notifications</h2>

      {error && (
        <div style={{ color: '#ef4444', marginBottom: 12, padding: 10, background: '#fef2f2', borderRadius: 6 }}>
          {error}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['inbox', 'preferences'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '6px 16px',
              borderRadius: 6,
              border: 'none',
              cursor: 'pointer',
              background: tab === t ? 'var(--color-primary, #6366f1)' : 'var(--color-surface-alt)',
              color: tab === t ? '#fff' : 'var(--color-on-surface)',
              fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t === 'inbox' ? `Inbox ${unreadCount > 0 ? `(${unreadCount})` : ''}` : 'Preferences'}
          </button>
        ))}
      </div>

      {tab === 'inbox' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <label style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(e) => setUnreadOnly(e.target.checked)}
              />
              Unread only
            </label>
            <button
              onClick={markAllRead}
              style={{
                marginLeft: 'auto', padding: '4px 12px', borderRadius: 5, border: 'none',
                cursor: 'pointer', background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)',
              }}
            >
              Mark all read
            </button>
            <button
              onClick={load}
              style={{ padding: '4px 12px', borderRadius: 5, border: 'none', cursor: 'pointer', background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)' }}
            >
              ↻ Refresh
            </button>
          </div>

          {loading && <div style={{ color: 'var(--color-on-muted)' }}>Loading…</div>}
          {!loading && notifications.length === 0 && (
            <div style={{ color: 'var(--color-on-muted)', fontStyle: 'italic' }}>No notifications.</div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {notifications.map((n) => (
              <div
                key={n.id}
                style={{
                  padding: '12px 16px',
                  borderRadius: 8,
                  background: n.read ? 'var(--color-surface)' : 'var(--color-surface-alt)',
                  border: `1px solid ${severityColor[n.severity]}40`,
                  borderLeft: `4px solid ${severityColor[n.severity]}`,
                  display: 'flex',
                  gap: 12,
                  alignItems: 'flex-start',
                }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: n.read ? 400 : 600, marginBottom: 2 }}>{n.title}</div>
                  <div style={{ fontSize: 13, color: 'var(--color-on-muted)' }}>{n.body}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-on-muted)', marginTop: 4 }}>
                    {n.notification_type} · {new Date(n.created_at).toLocaleString()}
                  </div>
                </div>
                {!n.read && (
                  <button
                    onClick={() => markRead(n.id)}
                    style={{ padding: '3px 10px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 12, background: 'var(--color-surface-alt)' }}
                  >
                    Mark read
                  </button>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {tab === 'preferences' && (
        <div>
          <p style={{ marginBottom: 12, color: 'var(--color-on-muted)', fontSize: 13 }}>
            Toggle notification types on/off. Use <code>*</code> as the wildcard default.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {preferences.map((pref) => (
              <div
                key={pref.notification_type}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '10px 14px',
                  background: 'var(--color-surface)',
                  borderRadius: 8,
                  border: '1px solid var(--color-border)',
                }}
              >
                <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
                  <input
                    type="checkbox"
                    checked={pref.enabled}
                    onChange={() => togglePreference(pref)}
                  />
                  <code style={{ fontSize: 13 }}>{pref.notification_type}</code>
                </label>
                <span style={{ fontSize: 12, color: 'var(--color-on-muted)' }}>
                  {pref.channels.join(', ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
