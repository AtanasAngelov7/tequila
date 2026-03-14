import React, { useState, useRef, useCallback } from 'react';

interface MessageInputProps {
  onSend: (content: string) => void;
}

export default function MessageInput({ onSend }: MessageInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue('');
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, onSend]);

  const handleKeyDown = (ev: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      submit();
    }
    // Shift+Enter = newline (default browser textarea behaviour)
  };

  const handleInput = (ev: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(ev.target.value);
    // Auto-resize
    const el = ev.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div
      style={{
        borderTop: '1px solid var(--color-border)',
        padding: '10px 16px',
        display: 'flex',
        gap: 8,
        alignItems: 'flex-end',
      }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
        rows={1}
        style={{
          flex: 1,
          resize: 'none',
          padding: '8px 12px',
          borderRadius: 8,
          border: '1px solid var(--color-border)',
          backgroundColor: 'var(--color-surface)',
          color: 'var(--color-on-surface)',
          fontSize: 13,
          fontFamily: 'inherit',
          lineHeight: 1.5,
          outline: 'none',
          overflowY: 'hidden',
        }}
      />
      <button
        onClick={submit}
        disabled={!value.trim()}
        title="Send (Enter)"
        style={{
          padding: '8px 16px',
          backgroundColor: value.trim() ? 'var(--color-primary)' : 'var(--color-border)',
          color: value.trim() ? '#fff' : 'var(--color-on-surface)',
          border: 'none',
          borderRadius: 8,
          cursor: value.trim() ? 'pointer' : 'default',
          fontSize: 13,
          fontWeight: 500,
          flexShrink: 0,
        }}
      >
        Send
      </button>
    </div>
  );
}
