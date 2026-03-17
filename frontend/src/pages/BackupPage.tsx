/**
 * BackupPage — create/restore backups, configure schedule (Sprint 14b D5).
 * Route: /backup
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';

interface BackupInfo {
  filename: string;
  path: string;
  size_bytes: number;
  created_at: string;
}

interface BackupConfig {
  enabled: boolean;
  schedule_cron: string;
  retention_count: number;
  backup_dir: string;
}

export default function BackupPage() {
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [config, setConfig] = useState<BackupConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editConfig, setEditConfig] = useState(false);
  const [configForm, setConfigForm] = useState<BackupConfig | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [bk, cfg] = await Promise.all([
        api.get<BackupInfo[]>('/backup/list'),
        api.get<BackupConfig>('/backup/config'),
      ]);
      setBackups(bk);
      setConfig(cfg);
      setConfigForm(cfg);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const createBackup = async () => {
    setCreating(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.post<{ filename: string }>('/backup/create', {});
      setSuccess(`Backup created: ${result.filename}`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  const handleRestoreFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!window.confirm(`Restore from "${file.name}"? This will overwrite your current data.`)) {
      return;
    }
    setRestoring(true);
    setError(null);
    setSuccess(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = (import.meta as any).env?.VITE_GATEWAY_TOKEN ?? '';
      const res = await fetch('/api/backup/restore', {
        method: 'POST',
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: formData,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const result = await res.json();
      setSuccess(`Restore complete. Steps: ${result.steps?.join(' → ')}`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setRestoring(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const saveConfig = async () => {
    if (!configForm) return;
    try {
      await api.patch('/backup/config', configForm);
      setSuccess('Configuration saved.');
      setEditConfig(false);
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const formatBytes = (b: number) => {
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 16 }}>💾 Backup & Restore</h2>

      {error && (
        <div style={{ color: '#ef4444', marginBottom: 12, padding: 10, background: '#fef2f2', borderRadius: 6 }}>
          {error}
        </div>
      )}
      {success && (
        <div style={{ color: '#22c55e', marginBottom: 12, padding: 10, background: '#f0fdf4', borderRadius: 6 }}>
          {success}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 24, flexWrap: 'wrap' }}>
        <button
          onClick={createBackup}
          disabled={creating}
          style={{ padding: '8px 20px', borderRadius: 7, border: 'none', cursor: 'pointer', background: 'var(--color-primary, #6366f1)', color: '#fff', fontWeight: 600 }}
        >
          {creating ? 'Creating…' : '+ Create Backup Now'}
        </button>
        <label style={{ padding: '8px 20px', borderRadius: 7, border: '1px solid var(--color-border)', cursor: 'pointer', fontWeight: 600, background: 'var(--color-surface)', color: 'var(--color-on-surface)' }}>
          {restoring ? 'Restoring…' : '↩ Restore from File'}
          <input
            ref={fileInputRef}
            type="file"
            accept=".tar.gz,.gz"
            style={{ display: 'none' }}
            onChange={handleRestoreFile}
          />
        </label>
        <button onClick={load} style={{ padding: '8px 16px', borderRadius: 7, border: 'none', cursor: 'pointer', background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)' }}>
          ↻ Refresh
        </button>
      </div>

      {/* Backup list */}
      <h3 style={{ marginBottom: 10 }}>Backup Files</h3>
      {loading && <div style={{ color: 'var(--color-on-muted)' }}>Loading…</div>}
      {!loading && backups.length === 0 && (
        <div style={{ color: 'var(--color-on-muted)', fontStyle: 'italic', marginBottom: 24 }}>No backups found.</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
        {backups.map((b) => (
          <div
            key={b.filename}
            style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 8, background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 600 }}>{b.filename}</div>
              <div style={{ fontSize: 12, color: 'var(--color-on-muted)' }}>
                {formatBytes(b.size_bytes)} · {new Date(b.created_at).toLocaleString()}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Configuration */}
      <h3 style={{ marginBottom: 10 }}>Schedule Configuration</h3>
      {config && !editConfig && (
        <div style={{ padding: '12px 16px', borderRadius: 8, background: 'var(--color-surface)', border: '1px solid var(--color-border)', marginBottom: 12 }}>
          <ConfigRow label="Enabled" value={config.enabled ? 'Yes' : 'No'} />
          <ConfigRow label="Schedule (cron)" value={config.schedule_cron} />
          <ConfigRow label="Retention count" value={String(config.retention_count)} />
          <ConfigRow label="Backup directory" value={config.backup_dir} />
          <button
            onClick={() => setEditConfig(true)}
            style={{ marginTop: 10, padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)' }}
          >
            Edit
          </button>
        </div>
      )}
      {editConfig && configForm && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--color-surface)', border: '1px solid var(--color-border)', marginBottom: 12 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label style={labelStyle}>
              Enabled
              <input type="checkbox" checked={configForm.enabled} onChange={(e) => setConfigForm({ ...configForm, enabled: e.target.checked })} />
            </label>
            <label style={labelStyle}>
              Schedule (cron)
              <input value={configForm.schedule_cron} onChange={(e) => setConfigForm({ ...configForm, schedule_cron: e.target.value })} style={inputStyle} />
            </label>
            <label style={labelStyle}>
              Retention count
              <input type="number" min="1" value={configForm.retention_count} onChange={(e) => setConfigForm({ ...configForm, retention_count: parseInt(e.target.value) || 1 })} style={{ ...inputStyle, width: 80 }} />
            </label>
            <label style={labelStyle}>
              Backup directory
              <input value={configForm.backup_dir} onChange={(e) => setConfigForm({ ...configForm, backup_dir: e.target.value })} style={inputStyle} />
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={saveConfig} style={{ padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer', background: 'var(--color-primary, #6366f1)', color: '#fff' }}>Save</button>
              <button onClick={() => setEditConfig(false)} style={{ padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer', background: 'var(--color-surface-alt)', color: 'var(--color-on-surface)' }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 14 }}>
      <span style={{ color: 'var(--color-on-muted)' }}>{label}</span>
      <code style={{ fontSize: 13 }}>{value}</code>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)',
  background: 'var(--color-surface)', color: 'var(--color-on-surface)', fontSize: 13,
};

const labelStyle: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13,
};
