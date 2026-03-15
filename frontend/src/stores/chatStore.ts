import { create } from 'zustand';
import { api } from '../api/client';
import { wsClient } from '../api/ws';
import type { Session, Message, TurnPhase, PendingApproval } from '../types';

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

  // Streaming state (Sprint 05)
  streamingContent: string;
  turnPhase: TurnPhase;
  isStreaming: boolean;
  pendingApproval: PendingApproval | null;
  activeToolCallId: string | null;
  activeToolName: string | null;

  loadSessions: (filters?: SessionFilters) => Promise<void>;
  createSession: (title?: string) => Promise<Session>;
  setActiveSession: (sessionId: string) => Promise<void>;
  loadMessages: (sessionId: string) => Promise<void>;
  sendMessage: (content: string) => void;
  receiveMessage: (msg: Message) => void;
  renameSession: (sessionId: string, title: string) => Promise<void>;

  // Sprint 05 actions
  setFeedback: (messageId: string, rating: 'up' | 'down', note?: string) => Promise<void>;
  clearFeedback: (messageId: string) => Promise<void>;
  regenerate: (sessionId: string, messageId: string) => Promise<void>;
  editAndResubmit: (sessionId: string, messageId: string, newContent: string) => Promise<void>;
  approveToolCall: (toolCallId: string) => void;
  denyToolCall: (toolCallId: string) => void;
  allowAllTools: () => void;
  _appendStreamText: (text: string) => void;
  _finalizeStream: (content?: string) => void;
  _setPendingApproval: (approval: PendingApproval | null) => void;
  _setTurnPhase: (phase: TurnPhase) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  isLoadingSessions: false,
  isLoadingMessages: false,
  streamingContent: '',
  turnPhase: 'idle',
  isStreaming: false,
  pendingApproval: null,
  activeToolCallId: null,
  activeToolName: null,

  loadSessions: async (filters?: SessionFilters) => {
    set({ isLoadingSessions: true });
    try {
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
    wsClient.send({
      method: 'session.resume',
      id: crypto.randomUUID(),
      payload: { session_key: session.session_key },
    });
    return session;
  },

  setActiveSession: async (sessionId: string) => {
    set({ activeSessionId: sessionId, messages: [], streamingContent: '', turnPhase: 'idle', isStreaming: false });
    await get().loadMessages(sessionId);
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
    set({ turnPhase: 'thinking', isStreaming: true, streamingContent: '' });
    wsClient.send({
      method: 'message.send',
      id: crypto.randomUUID(),
      payload: { session_key: session.session_key, role: 'user', content },
    });
  },

  receiveMessage: (msg: Message) => {
    set((s) => {
      if (msg.session_id !== s.activeSessionId) return s;
      // Replace optimistic message if same id, otherwise append
      const exists = s.messages.some((m) => m.id === msg.id);
      if (exists) {
        return { messages: s.messages.map((m) => m.id === msg.id ? msg : m) };
      }
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

  // ── Sprint 05 feedback ──────────────────────────────────────────────────────

  setFeedback: async (messageId: string, rating: 'up' | 'down', note?: string) => {
    const updated = await api.patch<Message>(`/messages/${messageId}/feedback`, { rating, note });
    set((s) => ({
      messages: s.messages.map((m) => m.id === messageId ? updated : m),
    }));
  },

  clearFeedback: async (messageId: string) => {
    const updated = await api.delete<Message>(`/messages/${messageId}/feedback`);
    set((s) => ({
      messages: s.messages.map((m) => m.id === messageId ? updated : m),
    }));
  },

  // ── Sprint 05 branching ─────────────────────────────────────────────────────

  regenerate: async (sessionId: string, messageId: string) => {
    await api.post(`/sessions/${sessionId}/regenerate`, { message_id: messageId });
    set({ turnPhase: 'thinking', isStreaming: true, streamingContent: '' });
  },

  editAndResubmit: async (sessionId: string, messageId: string, newContent: string) => {
    await api.post(`/sessions/${sessionId}/edit`, { message_id: messageId, content: newContent });
    set({ turnPhase: 'thinking', isStreaming: true, streamingContent: '' });
  },

  // ── Sprint 05 approval ──────────────────────────────────────────────────────

  approveToolCall: (toolCallId: string) => {
    const { sessions, activeSessionId } = get();
    const session = sessions.find((s) => s.session_id === activeSessionId);
    wsClient.send({
      method: 'approval.respond',
      id: crypto.randomUUID(),
      payload: { tool_call_id: toolCallId, approved: true, session_key: session?.session_key },
    });
    set({ pendingApproval: null });
  },

  denyToolCall: (toolCallId: string) => {
    const { sessions, activeSessionId } = get();
    const session = sessions.find((s) => s.session_id === activeSessionId);
    wsClient.send({
      method: 'approval.respond',
      id: crypto.randomUUID(),
      payload: { tool_call_id: toolCallId, approved: false, session_key: session?.session_key },
    });
    set({ pendingApproval: null });
  },

  allowAllTools: () => {
    const { sessions, activeSessionId, pendingApproval } = get();
    const session = sessions.find((s) => s.session_id === activeSessionId);
    wsClient.send({
      method: 'approval.respond',
      id: crypto.randomUUID(),
      payload: {
        tool_call_id: pendingApproval?.tool_call_id ?? '',
        approved: true,
        allow_all: true,
        session_key: session?.session_key,
      },
    });
    set({ pendingApproval: null });
  },

  // ── Internal stream handlers ───────────────────────────────────────────────

  _appendStreamText: (text: string) => {
    set((s) => ({ streamingContent: s.streamingContent + text, turnPhase: 'responding' }));
  },

  _finalizeStream: (content?: string) => {
    set({ isStreaming: false, turnPhase: 'idle', streamingContent: '', pendingApproval: null });
    // Reload messages to get the persisted assistant message
    const { activeSessionId, loadMessages } = get();
    if (activeSessionId) {
      void loadMessages(activeSessionId);
    }
  },

  _setPendingApproval: (approval) => set({ pendingApproval: approval }),
  _setTurnPhase: (phase) => set({ turnPhase: phase }),
}));

// ── WS frame routing (Sprint 05) ──────────────────────────────────────────────

import { wsClient as _wc } from '../api/ws';
import type { StreamPayload } from '../types';

_wc.onFrame((frame) => {
  const store = useChatStore.getState();

  // Persisted message echo
  if (frame.event === 'message.created' && frame.payload) {
    store.receiveMessage(frame.payload as unknown as Message);
    return;
  }

  // Agent run events
  if (frame.event === 'agent.run.start') {
    store._setTurnPhase('thinking');
    return;
  }

  if (frame.event === 'agent.run.stream' && frame.payload) {
    const sp = frame.payload as unknown as StreamPayload;
    switch (sp.kind) {
      case 'text_delta':
        if (sp.text) store._appendStreamText(sp.text);
        break;
      case 'thinking':
        if (sp.text) store._setTurnPhase('thinking');
        break;
      case 'tool_call_start':
        useChatStore.setState({
          turnPhase: 'tool_calling',
          activeToolCallId: sp.tool_call_id ?? null,
          activeToolName: sp.tool_name ?? null,
        });
        break;
      case 'tool_result':
        useChatStore.setState({ turnPhase: 'responding', activeToolCallId: null, activeToolName: null });
        break;
      case 'approval_request':
        store._setPendingApproval({
          tool_call_id: sp.tool_call_id ?? '',
          tool_name: sp.tool_name ?? '',
        });
        break;
      case 'approval_resolved':
        store._setPendingApproval(null);
        break;
      case 'error':
        console.error('Agent stream error:', sp.error_message);
        useChatStore.setState({ isStreaming: false, turnPhase: 'idle' });
        break;
    }
    return;
  }

  if (frame.event === 'agent.run.complete') {
    store._finalizeStream();
    return;
  }

  if (frame.event === 'agent.run.error') {
    useChatStore.setState({ isStreaming: false, turnPhase: 'idle' });
    return;
  }
});


