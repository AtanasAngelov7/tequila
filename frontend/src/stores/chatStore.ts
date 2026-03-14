import { create } from 'zustand';
import { api } from '../api/client';
import { wsClient } from '../api/ws';
import type { Session, Message } from '../types';

export interface SessionFilters {
  q?: string;
  status?: string;
  kind?: string;
  sort?: string;
  order?: string;
  limit?: number;
  offset?: number;
}

interface ChatState {
  sessions: Session[];
  activeSessionId: string | null;
  messages: Message[];
  isLoadingSessions: boolean;
  isLoadingMessages: boolean;

  loadSessions: (filters?: SessionFilters) => Promise<void>;
  createSession: (title?: string) => Promise<Session>;
  setActiveSession: (sessionId: string) => Promise<void>;
  loadMessages: (sessionId: string) => Promise<void>;
  sendMessage: (content: string) => void;
  receiveMessage: (msg: Message) => void;
  renameSession: (sessionId: string, title: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  isLoadingSessions: false,
  isLoadingMessages: false,

  loadSessions: async (filters?: SessionFilters) => {
    set({ isLoadingSessions: true });
    try {
      // Build query string from filters
      const params = new URLSearchParams();
      if (filters?.q) params.set('q', filters.q);
      if (filters?.status) params.set('status', filters.status);
      if (filters?.kind) params.set('kind', filters.kind);
      if (filters?.sort) params.set('sort', filters.sort);
      if (filters?.order) params.set('order', filters.order);
      if (filters?.limit != null) params.set('limit', String(filters.limit));
      if (filters?.offset != null) params.set('offset', String(filters.offset));
      const qs = params.toString();
      const url = qs ? `/sessions?${qs}` : '/sessions?status=active';
      const data = await api.get<{ sessions: Session[]; total: number }>(url);
      set({ sessions: data.sessions });
    } finally {
      set({ isLoadingSessions: false });
    }
  },

  createSession: async (title?: string) => {
    const session = await api.post<Session>('/sessions', {
      kind: 'user',
      channel: 'webchat',
      title: title ?? null,
    });
    set((s) => ({ sessions: [session, ...s.sessions] }));
    // Also resume via WS
    wsClient.send({
      method: 'session.resume',
      id: crypto.randomUUID(),
      payload: { session_key: session.session_key },
    });
    return session;
  },

  setActiveSession: async (sessionId: string) => {
    set({ activeSessionId: sessionId, messages: [] });
    await get().loadMessages(sessionId);
    // Inform WS layer
    const session = get().sessions.find((s) => s.session_id === sessionId);
    if (session) {
      wsClient.send({
        method: 'session.resume',
        id: crypto.randomUUID(),
        payload: { session_key: session.session_key },
      });
    }
  },

  loadMessages: async (sessionId: string) => {
    set({ isLoadingMessages: true });
    try {
      const data = await api.get<{ messages: Message[]; total: number }>(
        `/sessions/${sessionId}/messages`,
      );
      set({ messages: data.messages });
    } finally {
      set({ isLoadingMessages: false });
    }
  },

  sendMessage: (content: string) => {
    const { activeSessionId, sessions } = get();
    if (!activeSessionId) return;
    const session = sessions.find((s) => s.session_id === activeSessionId);
    if (!session) return;
    wsClient.send({
      method: 'message.send',
      id: crypto.randomUUID(),
      payload: { session_key: session.session_key, role: 'user', content },
    });
  },

  receiveMessage: (msg: Message) => {
    set((s) => {
      if (msg.session_id !== s.activeSessionId) return s;
      return { messages: [...s.messages, msg] };
    });
  },

  renameSession: async (sessionId: string, title: string) => {
    const updated = await api.patch<Session>(`/sessions/${sessionId}`, { title });
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.session_id === sessionId ? { ...sess, title: updated.title } : sess,
      ),
    }));
  },
}));

// Listen for message.created events from WS and push into chat store
import { wsClient as _wc } from '../api/ws';
_wc.onFrame((frame) => {
  if (frame.event === 'message.created' && frame.payload) {
    useChatStore.getState().receiveMessage(frame.payload as unknown as Message);
  }
});

