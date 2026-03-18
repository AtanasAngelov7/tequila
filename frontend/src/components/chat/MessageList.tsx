import { useCallback, useEffect, useRef, useState } from 'react';
import { useChatStore } from '../../stores/chatStore';
import StreamingMessage from './StreamingMessage';
import ToolCallDisplay from './ToolCallDisplay';
import InlineMedia from './InlineMedia';
import type { Message } from '../../types';

const roleColors: Record<string, string> = {
  user: 'var(--color-msg-user)',
  assistant: 'var(--color-msg-assistant)',
  system: 'var(--color-border)',
  tool_result: 'var(--color-border)',
};

// ── Feedback buttons ──────────────────────────────────────────────────────────

function FeedbackButtons({ message }: { message: Message }) {
  const { setFeedback, clearFeedback } = useChatStore();
  const rating = message.feedback?.rating ?? null;

  const toggle = (r: 'up' | 'down') => {
    if (rating === r) clearFeedback(message.id);
    else setFeedback(message.id, r);
  };

  return (
    <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
      <button
        onClick={() => toggle('up')}
        title={rating === 'up' ? 'Remove thumbs-up' : 'Thumbs up'}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: 14,
          opacity: rating === 'up' ? 1 : 0.35,
          padding: '0 2px',
          lineHeight: 1,
        }}
      >
        👍
      </button>
      <button
        onClick={() => toggle('down')}
        title={rating === 'down' ? 'Remove thumbs-down' : 'Thumbs down'}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: 14,
          opacity: rating === 'down' ? 1 : 0.35,
          padding: '0 2px',
          lineHeight: 1,
        }}
      >
        👎
      </button>
    </div>
  );
}

// ── Regenerate button ─────────────────────────────────────────────────────────

function RegenerateButton({ message }: { message: Message }) {
  const { activeSessionId, regenerate } = useChatStore();
  if (!activeSessionId) return null;

  return (
    <button
      onClick={() => regenerate(activeSessionId, message.id)}
      title="Regenerate response"
      style={{
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        fontSize: 11,
        opacity: 0.4,
        padding: '2px 4px',
        marginTop: 2,
        borderRadius: 4,
      }}
    >
      ↺ Regenerate
    </button>
  );
}

// ── Edit-and-resubmit ─────────────────────────────────────────────────────────

function EditButton({ message }: { message: Message }) {
  const { activeSessionId, editAndResubmit } = useChatStore();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  if (!activeSessionId) return null;

  const submit = () => {
    if (draft.trim()) {
      editAndResubmit(activeSessionId, message.id, draft.trim());
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <div style={{ marginTop: 6 }}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          style={{
            width: '100%',
            minHeight: 60,
            borderRadius: 6,
            border: '1px solid var(--color-border)',
            padding: '6px 8px',
            fontSize: 12,
            resize: 'vertical',
          }}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit();
            if (e.key === 'Escape') setEditing(false);
          }}
        />
        <div style={{ display: 'flex', gap: 6, marginTop: 4, justifyContent: 'flex-end' }}>
          <button
            onClick={() => setEditing(false)}
            style={{ fontSize: 11, padding: '2px 8px', cursor: 'pointer', borderRadius: 4, border: '1px solid var(--color-border)', background: 'none' }}
          >
            Cancel
          </button>
          <button
            onClick={submit}
            style={{ fontSize: 11, padding: '2px 8px', cursor: 'pointer', borderRadius: 4, border: 'none', background: 'var(--color-accent, #3b82f6)', color: '#fff' }}
          >
            Submit
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={() => { setDraft(message.content); setEditing(true); }}
      title="Edit and resubmit"
      style={{
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        fontSize: 11,
        opacity: 0.4,
        padding: '2px 4px',
        marginTop: 2,
        borderRadius: 4,
      }}
    >
      ✎ Edit
    </button>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';

  return (
    <div
      key={msg.id}
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        alignItems: 'flex-start',
        gap: 8,
      }}
    >
      <div style={{ maxWidth: '75%' }}>
        <div
          style={{
            padding: '9px 13px',
            borderRadius: 10,
            backgroundColor: roleColors[msg.role] ?? 'var(--color-border)',
            fontSize: 13,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {msg.content}

          {/* Inline media (images, audio, PDFs, code files) */}
          {msg.content_blocks && msg.content_blocks.length > 0 && (
            <InlineMedia blocks={msg.content_blocks} />
          )}

          {/* Tool calls (assistant messages) */}
          {msg.tool_calls && msg.tool_calls.length > 0 && (
            <div style={{ marginTop: 6 }}>
              {msg.tool_calls.map((tc) => (
                <ToolCallDisplay key={tc.tool_call_id} toolCall={tc} />
              ))}
            </div>
          )}
        </div>

        {/* Actions row */}
        <div
          style={{
            display: 'flex',
            gap: 4,
            justifyContent: isUser ? 'flex-end' : 'flex-start',
            flexWrap: 'wrap',
          }}
        >
          {msg.role === 'assistant' && (
            <>
              <FeedbackButtons message={msg} />
              <RegenerateButton message={msg} />
            </>
          )}
          {msg.role === 'user' && <EditButton message={msg} />}
        </div>
      </div>
    </div>
  );
}

// ── MessageList ───────────────────────────────────────────────────────────────

export default function MessageList() {
  const { messages, isLoadingMessages, isStreaming, streamingContent } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottom = useRef(true);
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track whether user is near the bottom of the scroll container
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  // TD-251: Debounce auto-scroll; only scroll if user was already at bottom
  useEffect(() => {
    if (!isNearBottom.current) return;
    if (scrollTimer.current) clearTimeout(scrollTimer.current);
    scrollTimer.current = setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 120);
    return () => { if (scrollTimer.current) clearTimeout(scrollTimer.current); };
  }, [messages, streamingContent]);

  if (isLoadingMessages) {
    return (
      <div style={{ flex: 1, padding: 16, opacity: 0.5, fontSize: 13 }}>
        Loading messages…
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {messages.length === 0 && !isStreaming && (
        <div style={{ opacity: 0.4, fontSize: 13, textAlign: 'center', marginTop: 40 }}>
          No messages yet. Say something!
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} msg={msg} />
      ))}

      {/* Streaming placeholder */}
      {isStreaming && <StreamingMessage content={streamingContent} />}

      <div ref={bottomRef} />
    </div>
  );
}
