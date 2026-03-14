/**
 * ConnectionStatus — small coloured dot in the top bar indicating WebSocket
 * connection state (§13.3 / §D2 Sprint 03).
 *
 * ● green  — connected
 * ● yellow — connecting
 * ● red    — disconnected
 */
import React from 'react';
import { useWsStore } from '../stores/wsStore';

export default function ConnectionStatus() {
  const status = useWsStore((s) => s.status);

  const color =
    status === 'connected' ? '#16a34a' : status === 'connecting' ? '#d97706' : '#dc2626';

  const label =
    status === 'connected'
      ? 'Connected'
      : status === 'connecting'
      ? 'Connecting…'
      : 'Disconnected';

  return (
    <div
      title={`Gateway: ${label}`}
      style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, opacity: 0.8 }}
    >
      <span
        style={{
          display: 'inline-block',
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: color,
          boxShadow: status === 'connected' ? `0 0 4px ${color}` : 'none',
          flexShrink: 0,
        }}
        aria-label={`Connection status: ${label}`}
      />
      <span style={{ color: 'var(--color-on-surface)', fontSize: 11 }}>{label}</span>
    </div>
  );
}
