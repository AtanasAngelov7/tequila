// File management API — Sprint 15 (§21.6, §21.7, §9.2b)
import { api, getAuthHeaders } from './client';

export interface FileRecord {
  file_id: string;
  session_id: string;
  file_path: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  origin: 'upload' | 'agent_generated';
  pinned: boolean;
  deleted: boolean;
  created_at: string;
}

export interface FileStats {
  total_files: number;
  total_size_mb: number;
  quota_mb: number;
  usage_percent: number;
  orphaned_files: number;
  orphaned_size_mb: number;
  pinned_files: number;
}

export const filesApi = {
  /** List all files for a session (uploads + agent-generated). */
  listSessionFiles: (sessionId: string) =>
    api.get<FileRecord[]>(`/sessions/${sessionId}/files`),

  /** Get storage statistics. */
  getStats: () => api.get<FileStats>('/files/stats'),

  /** Trigger a manual cleanup run — returns updated storage stats. */
  triggerCleanup: () => api.post<FileStats>('/files/cleanup', {}),

  /** Get preview URL for a file (thumbnail or first page). */
  previewUrl: (fileId: string) => `/api/files/${fileId}/preview`,

  /** Get download URL for a file. */
  downloadUrl: (fileId: string) => `/api/files/${fileId}/download`,

  /** Pin a file for permanent retention. */
  pin: (fileId: string) => api.post<void>(`/files/${fileId}/pin`, {}),

  /** Unpin a file. */
  unpin: (fileId: string) => api.delete<void>(`/files/${fileId}/pin`),

  /** Open file with OS default app (local-only action). */
  openFile: (fileId: string) => api.post<{ ok: boolean }>(`/files/${fileId}/open`, {}),

  /** Reveal file in Explorer (local-only action). */
  revealFile: (fileId: string) => api.post<{ ok: boolean }>(`/files/${fileId}/reveal`, {}),

  /** Download a file — triggers browser download. */
  download: (fileId: string, filename: string) => {
    const link = document.createElement('a');
    link.href = `/api/files/${fileId}/download`;
    link.download = filename;
    const headers = getAuthHeaders();
    const token = headers['X-Gateway-Token'];
    if (token) {
      // Fetch the file with auth header then create object URL
      fetch(`/api/files/${fileId}/download`, { headers: { 'X-Gateway-Token': token } })
        .then((r) => r.blob())
        .then((blob) => {
          const url = URL.createObjectURL(blob);
          link.href = url;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          setTimeout(() => URL.revokeObjectURL(url), 60_000);
        });
    } else {
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  },
};

/** Derive MIME category for display purposes. */
export function mimeCategory(mimeType: string): 'image' | 'pdf' | 'audio' | 'code' | 'other' {
  if (mimeType.startsWith('image/')) return 'image';
  if (mimeType === 'application/pdf') return 'pdf';
  if (mimeType.startsWith('audio/')) return 'audio';
  if (
    mimeType.startsWith('text/') ||
    mimeType === 'application/json' ||
    mimeType === 'application/javascript' ||
    mimeType === 'application/xml'
  )
    return 'code';
  return 'other';
}

/** Return a human-readable file size. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
