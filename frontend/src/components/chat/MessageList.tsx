import { useEffect, useRef } from 'react';
import { useChatStore } from '../../stores/chatStore';

const roleColors: Record<string, string> = {
  user: 'var(--color-msg-user)',
  assistant: 'var(--color-msg-assistant)',
  system: 'var(--color-border)',
  tool_result: 'var(--color-border)',
};

export default function MessageList() {
  const { messages, isLoadingMessages } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (isLoadingMessages) {
    return (
      <div style={{ flex: 1, padding: 16, opacity: 0.5, fontSize: 13 }}>
        Loading messages…
      </div>
    );
  }

  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {messages.length === 0 && (
        <div style={{ opacity: 0.4, fontSize: 13, textAlign: 'center', marginTop: 40 }}>
          No messages yet. Say something!
        </div>
      )}

      {messages.map((msg) => (
        <div
          key={msg.id}
          style={{
            display: 'flex',
            flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
            alignItems: 'flex-start',
            gap: 8,
          }}
        >
          <div
            style={{
              maxWidth: '75%',
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
          </div>
        </div>
      ))}

      <div ref={bottomRef} />
    </div>
  );
}
