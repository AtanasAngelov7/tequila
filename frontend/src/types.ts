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

export interface ContentBlock {
  type: 'text' | 'image' | 'file_ref';
  text?: string | null;
  file_id?: string | null;
  mime_type?: string | null;
  alt_text?: string | null;
}

export interface ToolCallOut {
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  success?: boolean | null;
  execution_time_ms?: number | null;
  approval_status?: string | null;
}

export interface MessageFeedback {
  rating: 'up' | 'down';
  note?: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool_result';
  content: string;
  content_blocks?: ContentBlock[];
  tool_calls?: ToolCallOut[] | null;
  tool_call_id?: string | null;
  file_ids?: string[];
  parent_id?: string | null;
  active?: boolean;
  provenance?: string;
  compressed?: boolean;
  model?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  feedback?: MessageFeedback | null;
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

// Stream events (agent.run.stream payload kinds)
export type StreamKind =
  | 'text_delta'
  | 'tool_call_start'
  | 'tool_call_input_delta'
  | 'tool_result'
  | 'approval_request'
  | 'approval_resolved'
  | 'thinking'
  | 'error';

export interface StreamPayload {
  kind: StreamKind;
  text?: string | null;
  tool_name?: string | null;
  tool_call_id?: string | null;
  tool_input?: Record<string, unknown> | null;
  tool_result?: Record<string, unknown> | null;
  approval_action?: 'approve' | 'deny' | null;
  error_message?: string | null;
}

// Turn state for the progress indicator
export type TurnPhase = 'idle' | 'thinking' | 'tool_calling' | 'responding';

export interface PendingApproval {
  tool_call_id: string;
  tool_name: string;
  tool_args?: Record<string, unknown>;  // TD-250: show args before approval
}
