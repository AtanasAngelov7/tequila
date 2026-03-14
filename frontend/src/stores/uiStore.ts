import { create } from 'zustand';
import type { Theme } from '../types';

interface UiState {
  sidebarOpen: boolean;
  theme: Theme;
  shortcutsHelpOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setTheme: (theme: Theme) => void;
  toggleShortcutsHelp: () => void;
  closeShortcutsHelp: () => void;

  // ── Session filter state (ephemeral, §9.5) ──────────────────────────
  sessionSearch: string;
  sessionStatus: string;
  sessionKind: string;
  sessionSort: string;
  sessionOrder: string;
  setSessionSearch: (q: string) => void;
  setSessionStatus: (status: string) => void;
  setSessionKind: (kind: string) => void;
  setSessionSort: (sort: string) => void;
  setSessionOrder: (order: string) => void;
  clearSessionFilters: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  theme: (localStorage.getItem('tequila.theme') as Theme) ?? 'system',
  shortcutsHelpOpen: false,

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),

  setTheme: (theme) => {
    localStorage.setItem('tequila.theme', theme);
    set({ theme });
  },

  toggleShortcutsHelp: () => set((s) => ({ shortcutsHelpOpen: !s.shortcutsHelpOpen })),
  closeShortcutsHelp: () => set({ shortcutsHelpOpen: false }),

  // ── Session filter state ─────────────────────────────────────────────
  sessionSearch: '',
  sessionStatus: 'active',
  sessionKind: '',
  sessionSort: 'last_activity',
  sessionOrder: 'desc',

  setSessionSearch: (q) => set({ sessionSearch: q }),
  setSessionStatus: (status) => set({ sessionStatus: status }),
  setSessionKind: (kind) => set({ sessionKind: kind }),
  setSessionSort: (sort) => set({ sessionSort: sort }),
  setSessionOrder: (order) => set({ sessionOrder: order }),
  clearSessionFilters: () =>
    set({
      sessionSearch: '',
      sessionStatus: 'active',
      sessionKind: '',
      sessionSort: 'last_activity',
      sessionOrder: 'desc',
    }),
}));
