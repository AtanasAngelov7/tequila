import { create } from 'zustand';
import { wsClient } from '../api/ws';
import type { WsFrame } from '../types';

type WsStatus = 'connecting' | 'connected' | 'disconnected';

interface WsState {
  status: WsStatus;
  lastSeq: number;
  lastFrame: WsFrame | null;
  setStatus: (status: WsStatus) => void;
  receiveFrame: (frame: WsFrame) => void;
  sendFrame: (frame: Omit<WsFrame, 'seq'>) => void;
}

export const useWsStore = create<WsState>((set) => ({
  status: 'disconnected',
  lastSeq: 0,
  lastFrame: null,

  setStatus: (status) => set({ status }),

  receiveFrame: (frame) =>
    set((s) => ({
      lastSeq: frame.seq ?? s.lastSeq,
      lastFrame: frame,
    })),

  sendFrame: (frame) => wsClient.send(frame),
}));

// Wire up the singleton client to the store
wsClient.onStatus((status) => useWsStore.getState().setStatus(status));
wsClient.onFrame((frame) => useWsStore.getState().receiveFrame(frame));
