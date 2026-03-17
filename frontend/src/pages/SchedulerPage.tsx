/**
 * SchedulerPage — manage cron-scheduled agent sessions (Sprint 13, D7).
 *
 * Accessible via /scheduler route.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

interface ScheduledTask {
  id: string;
  name: string;
  description: string | null;
  cron_expression: string;
  agent_id: string | null;
  prompt_template: string;
  enabled: boolean;
  announce: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  last_run_error: string | null;
  next_run_at: string | null;
  run_count: number;
  created_at: string;
}

interface CreateForm {
  name: string;
  description: string;
  cron_expression: string;
  agent_id: string;
  prompt_template: string;
  enabled: boolean;
  announce: boolean;
}

const EMPTY_FORM: CreateForm = {
  name: '',
  description: '',
  cron_expression: '0 9 * * 1',
  agent_id: '',
  prompt_template: 'Run your scheduled task. Current time: {now}',
  enabled: true,
  announce: false,
};

const CRON_PRESETS = [
  { label: 'Every minute', value: '* * * * *' },
  { label: 'Every 5 minutes', value: '*/5 * * * *' },
  { label: 'Hourly', value: '0 * * * *' },
  { label: 'Daily at 9am', value: '0 9 * * *' },
  { label: 'Weekdays at 9am', value: '0 9 * * 1-5' },
  { label: 'Weekly (Mon 9am)', value: '0 9 * * 1' },
  { label: 'Monthly (1st 9am)', value: '0 9 1 * *' },
];

const card: React.CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: 16,
};

const btn = (color = '#4a9eff', small = false): React.CSSProperties => ({
  padding: small ? '3px 8px' : '6px 14px',
  borderRadius: 5,
  border: 'none',
  background: color,
  color: '#fff',
  cursor: 'pointer',
  fontSize: small ? 11 : 13,
  fontWeight: 600,
});

const input: React.CSSProperties = {
  padding: '6px 10px',
  borderRadius: 5,
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)',
  color: 'var(--color-text)',
  fontSize: 13,
  width: '100%',
  boxSizing: 'border-box',
};

const label: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  color: 'var(--color-text-muted)',
  marginBottom: 4,
};

const STATUS_COLORS: Record<string, string> = {
  ok: '#22c55e',
  error: '#ef4444',
  skipped: '#f59e0b',
};

export default function SchedulerPage() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState<Set<string>>(new Set());

  const loadTasks = useCallback(async () => {
    try {
      const data = await api.get<{ tasks: ScheduledTask[] }>('/scheduled-tasks');
      setTasks(data.tasks);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTasks(); }, [loadTasks]);

  const handleCreate = async () => {
    setSaving(true);
    try {
      await api.post('/scheduled-tasks', form);
      setForm(EMPTY_FORM);
      setShowCreate(false);
      await loadTasks();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create task');
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (task: ScheduledTask) => {
    try {
      await api.patch(`/scheduled-tasks/${task.id}`, { enabled: !task.enabled });
      await loadTasks();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update task');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this scheduled task?')) return;
    try {
      await api.delete(`/scheduled-tasks/${id}`);
      await loadTasks();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to delete task');
    }
  };

  const handleRunNow = async (id: string) => {
    setRunning(prev => new Set(prev).add(id));
    try {
      await api.post(`/scheduled-tasks/${id}/run`, {});
      await loadTasks();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to trigger task');
    } finally {
      setRunning(prev => { const s = new Set(prev); s.delete(id); return s; });
    }
  };

  const fmtDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString() : '—';

  return (
    <div
      style={{
        padding: 24,
        maxWidth: 900,
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 20,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22 }}>⏰ Scheduler</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--color-text-muted)', fontSize: 13 }}>
            Schedule recurring agent sessions with cron expressions.
          </p>
        </div>
        <button style={btn()} onClick={() => setShowCreate(v => !v)}>
          {showCreate ? 'Cancel' : '＋ New Task'}
        </button>
      </div>

      {error && (
        <div
          style={{ padding: 12, borderRadius: 6, background: '#fee2e2', color: '#991b1b', fontSize: 13 }}
        >
          {error}
          <button
            onClick={() => setError(null)}
            style={{ marginLeft: 12, cursor: 'pointer', background: 'none', border: 'none', color: '#991b1b', fontWeight: 700 }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div style={{ ...card, border: '1px solid #4a9eff' }}>
          <h3 style={{ margin: '0 0 12px' }}>Create Scheduled Task</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <span style={label}>Name *</span>
              <input
                style={input}
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="Daily summary"
              />
            </div>
            <div>
              <span style={label}>Agent ID (optional)</span>
              <input
                style={input}
                value={form.agent_id}
                onChange={e => setForm(f => ({ ...f, agent_id: e.target.value }))}
                placeholder="Leave blank for default agent"
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <span style={label}>Cron Expression *</span>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  style={{ ...input, flex: 1 }}
                  value={form.cron_expression}
                  onChange={e => setForm(f => ({ ...f, cron_expression: e.target.value }))}
                  placeholder="0 9 * * 1"
                />
                <select
                  style={{ ...input, width: 'auto', cursor: 'pointer' }}
                  onChange={e => {
                    if (e.target.value) setForm(f => ({ ...f, cron_expression: e.target.value }));
                  }}
                  value=""
                >
                  <option value="">Presets…</option>
                  {CRON_PRESETS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--color-text-muted)' }}>
                Format: minute hour day-of-month month day-of-week
              </p>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <span style={label}>Prompt Template *</span>
              <textarea
                style={{ ...input, minHeight: 80, resize: 'vertical' }}
                value={form.prompt_template}
                onChange={e => setForm(f => ({ ...f, prompt_template: e.target.value }))}
                placeholder="The current date is {date}. Run your scheduled task."
              />
              <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--color-text-muted)' }}>
                Supports: {'{now}'}, {'{date}'}, {'{time}'}
              </p>
            </div>
            <div>
              <span style={label}>Description</span>
              <input
                style={input}
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                placeholder="Optional description"
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, justifyContent: 'flex-end' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
                />
                Enabled on creation
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={form.announce}
                  onChange={e => setForm(f => ({ ...f, announce: e.target.checked }))}
                />
                Announce runs to user
              </label>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button style={btn()} onClick={handleCreate} disabled={saving || !form.name || !form.cron_expression || !form.prompt_template}>
              {saving ? 'Creating…' : 'Create Task'}
            </button>
            <button style={btn('#6b7280')} onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Task list */}
      {loading ? (
        <p style={{ color: 'var(--color-text-muted)' }}>Loading…</p>
      ) : tasks.length === 0 ? (
        <div style={{ ...card, textAlign: 'center', padding: 40 }}>
          <p style={{ color: 'var(--color-text-muted)', margin: 0 }}>
            No scheduled tasks yet. Click <strong>＋ New Task</strong> to create one.
          </p>
        </div>
      ) : (
        tasks.map(task => (
          <div key={task.id} style={{ ...card, opacity: task.enabled ? 1 : 0.65 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <strong style={{ fontSize: 15 }}>{task.name}</strong>
                  <span
                    style={{
                      fontSize: 11,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: task.enabled ? '#dcfce7' : '#f3f4f6',
                      color: task.enabled ? '#166534' : '#6b7280',
                    }}
                  >
                    {task.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                  {task.last_run_status && (
                    <span
                      style={{
                        fontSize: 11,
                        padding: '2px 6px',
                        borderRadius: 4,
                        background: '#f3f4f6',
                        color: STATUS_COLORS[task.last_run_status] ?? '#6b7280',
                      }}
                    >
                      Last: {task.last_run_status}
                    </span>
                  )}
                </div>
                {task.description && (
                  <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--color-text-muted)' }}>
                    {task.description}
                  </p>
                )}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  style={btn('#22c55e', true)}
                  onClick={() => handleRunNow(task.id)}
                  disabled={running.has(task.id)}
                  title="Run now"
                >
                  {running.has(task.id) ? '…' : '▶ Run'}
                </button>
                <button
                  style={btn(task.enabled ? '#f59e0b' : '#4a9eff', true)}
                  onClick={() => handleToggle(task)}
                  title={task.enabled ? 'Disable' : 'Enable'}
                >
                  {task.enabled ? '⏸ Pause' : '▶ Enable'}
                </button>
                <button
                  style={btn('#ef4444', true)}
                  onClick={() => handleDelete(task.id)}
                  title="Delete"
                >
                  🗑
                </button>
              </div>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 8,
                marginTop: 8,
                fontSize: 12,
              }}
            >
              <div>
                <span style={{ color: 'var(--color-text-muted)' }}>Cron: </span>
                <code style={{ fontFamily: 'monospace', fontSize: 12 }}>{task.cron_expression}</code>
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)' }}>Last run: </span>
                {fmtDate(task.last_run_at)}
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)' }}>Next run: </span>
                {fmtDate(task.next_run_at)}
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)' }}>Runs: </span>
                {task.run_count}
              </div>
              {task.agent_id && (
                <div>
                  <span style={{ color: 'var(--color-text-muted)' }}>Agent: </span>
                  <code style={{ fontFamily: 'monospace', fontSize: 11 }}>{task.agent_id}</code>
                </div>
              )}
            </div>

            {task.last_run_error && (
              <div
                style={{
                  marginTop: 8,
                  padding: '6px 10px',
                  borderRadius: 4,
                  background: '#fee2e2',
                  color: '#991b1b',
                  fontSize: 12,
                  fontFamily: 'monospace',
                }}
              >
                Error: {task.last_run_error}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
