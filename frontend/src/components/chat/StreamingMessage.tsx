import { useEffect, useState } from 'react';

/**
 * StreamingMessage — shows the in-progress response with a blinking cursor.
 * Renders while isStreaming=true with the accumulated streamingContent.
 */
interface StreamingMessageProps {
  content: string;
}

export default function StreamingMessage({ content }: StreamingMessageProps) {
  const [showCursor, setShowCursor] = useState(true);

  // Blink cursor at 600ms interval
  useEffect(() => {
    const timer = setInterval(() => setShowCursor((v) => !v), 600);
    return () => clearInterval(timer);
  }, []);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
      }}
    >
      <div
        style={{
          maxWidth: '75%',
          padding: '9px 13px',
          borderRadius: 10,
          backgroundColor: 'var(--color-msg-assistant)',
          fontSize: 13,
          lineHeight: 1.5,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          opacity: 0.9,
        }}
      >
        {content}
        <span
          style={{
            display: 'inline-block',
            width: 2,
            height: '1em',
            backgroundColor: 'currentColor',
            marginLeft: 2,
            verticalAlign: 'text-bottom',
            opacity: showCursor ? 1 : 0,
            transition: 'opacity 0.1s',
          }}
        />
      </div>
    </div>
  );
}
