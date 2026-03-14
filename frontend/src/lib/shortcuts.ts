// Keyboard shortcut manager for Tequila
// Shortcuts per §9.4 of the specification.

export interface ShortcutDef {
  key: string;            // e.g. "k"
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  description: string;
  handler: () => void;
}

export class ShortcutManager {
  private shortcuts: ShortcutDef[] = [];
  private active = false;

  register(def: ShortcutDef): () => void {
    this.shortcuts.push(def);
    return () => {
      this.shortcuts = this.shortcuts.filter((s) => s !== def);
    };
  }

  /** Start listening for keyboard events. */
  mount(): void {
    if (this.active) return;
    this.active = true;
    window.addEventListener('keydown', this._onKeyDown);
  }

  /** Stop listening. */
  unmount(): void {
    this.active = false;
    window.removeEventListener('keydown', this._onKeyDown);
  }

  getAll(): Readonly<ShortcutDef[]> {
    return this.shortcuts;
  }

  private _onKeyDown = (ev: KeyboardEvent): void => {
    // Don't trigger when typing in an input/textarea (except Enter/Escape)
    const tag = (ev.target as HTMLElement).tagName;
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

    for (const s of this.shortcuts) {
      const ctrlMatch = !!s.ctrl === ev.ctrlKey;
      const shiftMatch = !!s.shift === ev.shiftKey;
      const altMatch = !!s.alt === ev.altKey;
      const keyMatch = ev.key.toLowerCase() === s.key.toLowerCase();

      if (ctrlMatch && shiftMatch && altMatch && keyMatch) {
        if (isInput && !['Escape', 'Enter'].includes(ev.key)) continue;
        ev.preventDefault();
        s.handler();
        return;
      }
    }
  };
}

export const shortcutManager = new ShortcutManager();
