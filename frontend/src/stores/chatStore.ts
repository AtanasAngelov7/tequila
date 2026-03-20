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
  turnError: string | null;  // visible error from last failed turn
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
  _setTurnError: (error: string | null) => void;
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
  turnError: null,
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
    // TD-249: Optimistic update — show placeholder immediately
    const tempId = `temp-${crypto.randomUUID()}`;
    const optimistic: Session = {
      session_id: tempId,
      session_key: '',
      title: title ?? 'New Session',
      status: 'active',
      kind: 'user',
      channel: 'webchat',
      message_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    } as Session;
    set((s) => ({ sessions: [optimistic, ...s.sessions] }));

    try {
      const session = await api.post<Session>('/sessions', {
        kind: 'user',
        channel: 'webchat',
        title: title ?? null,
      });
      // Replace optimistic placeholder with real session
      set((s) => ({
        sessions: s.sessions.map((sess) =>
          sess.session_id === tempId ? session : sess,
        ),
      }));
      wsClient.send({
        method: 'session.resume',
        id: crypto.randomUUID(),
        payload: { session_key: session.session_key },
      });
      return session;
    } catch (err) {
      // Rollback optimistic update on failure
      set((s) => ({
        sessions: s.sessions.filter((sess) => sess.session_id !== tempId),
      }));
      throw err;
    }
  },

  setActiveSession: async (sessionId: string) => {
    console.log('[chatStore] setActiveSession', sessionId);
    set({ activeSessionId: sessionId, messages: [], streamingContent: '', turnPhase: 'idle', isStreaming: false });
    await get().loadMessages(sessionId);
    const session = get().sessions.find((s) => s.session_id === sessionId);
    if (session) {
      console.log('[chatStore] sending session.resume key=%s', session.session_key.slice(0, 8));
      wsClient.send({
        method: 'session.resume',
        id: crypto.randomUUID(),
        payload: { session_key: session.session_key },
      });
    } else {
      console.warn('[chatStore] setActiveSession: session not found in sessions array for', sessionId);
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
    if (!activeSessionId) {
      console.warn('[chatStore] sendMessage: no activeSessionId — aborting');
      return;
    }
    const session = sessions.find((s) => s.session_id === activeSessionId);
    if (!session) {
      console.warn('[chatStore] sendMessage: session not found for', activeSessionId);
      return;
    }

    // Optimistic user message so the user sees their input immediately.
    const optimisticId = `opt-${crypto.randomUUID()}`;
    const optimisticMsg: Message = {
      id: optimisticId,
      session_id: activeSessionId,
      role: 'user',
      content,
      content_blocks: [],
      tool_calls: [],
      file_ids: [],
      active: true,
      provenance: 'user_input',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    set((s) => ({
      messages: [...s.messages, optimisticMsg],
      turnPhase: 'thinking' as const,
      isStreaming: true,
      streamingContent: '',
      turnError: null,
    }));
    console.log('[chatStore] sendMessage: dispatching message.send session_key=%s', session.session_key.slice(0, 8));
    wsClient.send({
      method: 'message.send',
      id: crypto.randomUUID(),
      payload: { session_key: session.session_key, role: 'user', content },
    });
  },

  receiveMessage: (msg: Message) => {
    set((s) => {
      if (msg.session_id !== s.activeSessionId) return s;
      // Replace optimistic message if same id, otherwise append.
      // Also replace optimistic user messages (id starts with "opt-") to avoid
      // duplicates when the server echoes the persisted message back.
      const exists = s.messages.some((m) => m.id === msg.id);
      if (exists) {
        return { messages: s.messages.map((m) => m.id === msg.id ? msg : m) };
      }
      // Replace the first optimistic placeholder that matches role+content
      if (msg.role === 'user') {
        const optIdx = s.messages.findIndex(
          (m) => m.id.startsWith('opt-') && m.role === 'user' && m.content === msg.content,
        );
        if (optIdx !== -1) {
          const updated = [...s.messages];
          updated[optIdx] = msg;
          return { messages: updated };
        }
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

  _finalizeStream: (_content?: string) => {
    set({ isStreaming: false, turnPhase: 'idle', streamingContent: '', pendingApproval: null });
    // Reload messages to get the persisted assistant message
    const { activeSessionId, loadMessages } = get();
    if (activeSessionId) {
      void loadMessages(activeSessionId);
    }
  },

  _setPendingApproval: (approval) => set({ pendingApproval: approval }),
  _setTurnPhase: (phase) => set({ turnPhase: phase }),
  _setTurnError: (error) => set({ turnError: error }),
}));

// ── WS frame routing (Sprint 05) ──────────────────────────────────────────────

import { wsClient as _wc } from '../api/ws';
import type { StreamPayload } from '../types';

_wc.onFrame((frame) => {
  const store = useChatStore.getState();

  // Persisted message echo
  if (frame.event === 'message.created' && frame.payload) {
    console.log('[chatStore] message.created received', frame.payload);
    // TD-254: Runtime validation of WS payload before cast
    const p = frame.payload as Record<string, unknown>;
    if (typeof p.id === 'string' && typeof p.role === 'string' && typeof p.content === 'string') {
      store.receiveMessage(p as unknown as Message);
    }
    return;
  }

  // Agent run events
  if (frame.event === 'agent.run.start') {
    console.log('[chatStore] agent.run.start — entering thinking phase');
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
    console.log('[chatStore] agent.run.complete — finalizing stream');
    store._finalizeStream();
    return;
  }

  if (frame.event === 'agent.run.error') {
    const errPayload = frame.payload as Record<string, unknown> | undefined;
    const msg = (errPayload?.error as string) || 'The AI response failed. Please try again.';
    console.error('[chatStore] agent.run.error:', msg);
    useChatStore.setState({ isStreaming: false, turnPhase: 'idle', turnError: msg });
    return;
  }
});


