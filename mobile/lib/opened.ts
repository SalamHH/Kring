/**
 * Which incidents have been opened on this device, for «N ny» on Hjem (F4). Kept on the device
 * only, in a small JSON file, never sent to the API. Entries older than 30 days are dropped,
 * since Hjem counts only the last 7.
 */
import { useSyncExternalStore } from 'react';

export interface TextFile {
  read(): string | null;
  write(text: string): void;
}

const KEEP_MS = 30 * 24 * 3600 * 1000;

export class OpenedStore {
  private opened: Map<string, number> | null = null;
  private listeners = new Set<() => void>();
  private version = 0;

  constructor(
    private readonly file: TextFile,
    private readonly now: () => number = Date.now,
  ) {}

  private load(): Map<string, number> {
    if (this.opened) return this.opened;
    this.opened = new Map();
    try {
      const raw = this.file.read();
      const parsed: unknown = raw ? JSON.parse(raw) : {};
      if (parsed && typeof parsed === 'object') {
        const cutoff = this.now() - KEEP_MS;
        for (const [id, at] of Object.entries(parsed as Record<string, unknown>)) {
          if (typeof at === 'number' && at >= cutoff) this.opened.set(id, at);
        }
      }
    } catch (e) {
      console.warn('opened: could not read the list; starting empty', e);
    }
    return this.opened;
  }

  isOpened = (id: string): boolean => this.load().has(id);

  markOpened(id: string): void {
    const opened = this.load();
    if (opened.has(id)) return;
    opened.set(id, this.now());
    try {
      this.file.write(JSON.stringify(Object.fromEntries(opened)));
    } catch (e) {
      console.warn('opened: could not save the list', e);
    }
    this.version++;
    this.listeners.forEach((l) => l());
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getVersion = (): number => this.version;
}

/** Re-renders when an incident is marked opened; returns the store's isOpened. */
export function useOpened(store: OpenedStore): (id: string) => boolean {
  useSyncExternalStore(store.subscribe, store.getVersion);
  return store.isOpened;
}
