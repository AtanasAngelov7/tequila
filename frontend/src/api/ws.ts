// WebSocket client with reconnection (exponential backoff) and seq tracking.
// Connects to /api/ws (proxied by Vite dev server to ws://localhost:8000/api/ws).

import type { WsFrame } from '../types';

type FrameHandler = (frame: WsFrame) => void;

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`;
const MAX_BACKOFF_MS = 30_000;

export class TequilaWsClient {
  private ws: WebSocket | null = null;
  private lastSeq = 0;
  private backoff = 1_000;
  private destroyed = false;
  private _pendingReconnect: ReturnType<typeof setTimeout> | null = null;
  // Track the active session_key (not session_id) so we can re-resume on reconnect.
  // The stores always send session.resume with session_key; session_id is never used.
  private _activeSessionKey: string | null = null;

  private listeners: Set<FrameHandler> = new Set();
  private statusListeners: Set<(status: 'connecting' | 'connected' | 'disconnected') => void> =
    new Set();

  /** Subscribe to incoming frames. Returns an unsubscribe function. */
  onFrame(fn: FrameHandler): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: (s: 'connecting' | 'connected' | 'disconnected') => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  connect() {
    if (this.destroyed) return;
    // Idempotent: skip if already open or handshaking (safe with React StrictMode).
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      console.log('[ws] connect() skipped — already %s', this.ws.readyState === WebSocket.OPEN ? 'OPEN' : 'CONNECTING');
      return;
    }
    console.log('[ws] connect() opening new WebSocket to', WS_URL);
    // Detach handlers from any previous (closed/closing) WS instance before
    // replacing it.  Without this, the old instance's onclose fires after we
    // assign the new WS, triggering a spurious _scheduleReconnect() and causing
    // a cascade of unwanted connections.
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
    }
    this._emit_status('connecting');
    this.ws = new WebSocket(WS_URL);

    this.ws.onopen = () => {
      this.backoff = 1_000;
      this._emit_status('connected');
      console.log('[ws] connected, sending handshake (last_seq=%d)', this.lastSeq);
      // Send connect handshake so server can replay missed events
      this._send({ method: 'connect', id: crypto.randomUUID(), payload: { last_seq: this.lastSeq } });
      // Re-resume the active session on reconnect so the server restores its
      // per-connection active_session_id / active_session_key state.
      if (this._activeSessionKey) {
        console.log('[ws] re-resuming session_key=%s on reconnect', this._activeSessionKey.slice(0, 8));
        this._send({ method: 'session.resume', id: crypto.randomUUID(), payload: { session_key: this._activeSessionKey } });
      }
      // TD-252: Flush queued messages that were sent while disconnected
      if (this._pendingQueue.length > 0) {
        const queued = this._pendingQueue.splice(0);
        for (const f of queued) {
          this.ws!.send(JSON.stringify(f));
        }
      }
    };

    this.ws.onmessage = (ev) => {
      try {
        const frame: WsFrame = JSON.parse(ev.data as string);
        if (frame.seq !== undefined) this.lastSeq = frame.seq;
        console.log('[ws] ← frame', frame.event ?? frame.id?.slice(0, 8), frame);
        this.listeners.forEach((fn) => fn(frame));
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = (ev) => {
      console.warn('[ws] closed code=%d reason=%s wasClean=%s', ev.code, ev.reason, ev.wasClean);
      if (this.destroyed) return;
      this._emit_status('disconnected');
      this._scheduleReconnect();
    };

    this.ws.onerror = (ev) => {
      console.error('[ws] error', ev);
      this.ws?.close();
    };
  }

  // TD-252: Queue messages when WS is not open and flush on reconnect
  private _pendingQueue: Omit<WsFrame, 'seq'>[] = [];

  send(frame: Omit<WsFrame, 'seq'>) {
    // Track the active session_key so we can re-resume it after any reconnect.
    const f = frame as any;
    if (f.method === 'session.resume' && f.payload?.session_key) {
      this._activeSessionKey = f.payload.session_key;
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.log('[ws] → send', f.method ?? 'response', frame);
      this.ws.send(JSON.stringify(frame));
    } else {
      console.warn('[ws] → queued (ws not open, readyState=%s)', this.ws?.readyState, f.method);
      this._pendingQueue.push(frame);
    }
  }

  destroy() {
    this.destroyed = true;
    if (this._pendingReconnect) clearTimeout(this._pendingReconnect);
    this.ws?.close();
  }

  private _send(frame: Omit<WsFrame, 'seq'>) {
    this.ws?.send(JSON.stringify(frame));
  }

  private _scheduleReconnect() {
    const delay = this.backoff + Math.random() * 200;
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
    this._pendingReconnect = setTimeout(() => this.connect(), delay);
  }

  private _emit_status(s: 'connecting' | 'connected' | 'disconnected') {
    this.statusListeners.forEach((fn) => fn(s));
  }
}

// Singleton used by the stores
export const wsClient = new TequilaWsClient();
