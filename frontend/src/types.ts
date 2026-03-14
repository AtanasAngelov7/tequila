// Shared TypeScript types matching the backend Pydantic models

export interface Session {
  session_id: string;
  session_key: string;
  kind: string;
  agent_id: string | null;
  channel: string;
  status: 'active' | 'idle' | 'archived';
  title: string | null;
  summary: string | null;
  message_count: number;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool_result';
  content: string;
  created_at: string;
  updated_at: string | null;
}

export type Theme = 'light' | 'dark' | 'system';

export interface WsFrame {
  event?: string;
  method?: string;
  id?: string;
  ok?: boolean;
  payload?: Record<string, unknown>;
  seq?: number;
  error?: string | null;
}
