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
  private _activeSessionId: string | null = null;

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
    this._emit_status('connecting');
    this.ws = new WebSocket(WS_URL);

    this.ws.onopen = () => {
      this.backoff = 1_000;
      this._emit_status('connected');
      // Send connect handshake so server can replay missed events
      this._send({ method: 'connect', id: crypto.randomUUID(), payload: { last_seq: this.lastSeq } });
      // TD-230: Re-resume active session on reconnect
      if (this._activeSessionId) {
        this._send({ method: 'session.resume', id: crypto.randomUUID(), payload: { session_id: this._activeSessionId } });
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
        this.listeners.forEach((fn) => fn(frame));
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = () => {
      if (this.destroyed) return;
      this._emit_status('disconnected');
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  // TD-252: Queue messages when WS is not open and flush on reconnect
  private _pendingQueue: Omit<WsFrame, 'seq'>[] = [];

  send(frame: Omit<WsFrame, 'seq'>) {
    // TD-230: Track which session is active for reconnect resume
    const f = frame as any;
    if (f.method === 'session.resume' && f.payload?.session_id) {
      this._activeSessionId = f.payload.session_id;
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    } else {
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
