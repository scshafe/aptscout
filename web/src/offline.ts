import type { ApartmentInput } from "./api";

const KEY = "aptscout.queue.v1";

export interface Queued {
  id: string;
  at: string;
  body: ApartmentInput;
  error?: string;
}

/** The slice of localStorage used, so tests can pass a fake. */
export interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function defaultStore(): Store | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;  // private mode or blocked site data
  }
}

export function load(store: Store | undefined = defaultStore()): Queued[] {
  try {
    return JSON.parse(store?.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

function save(items: Queued[], store: Store | undefined = defaultStore()) {
  store?.setItem(KEY, JSON.stringify(items));
}

export function enqueue(body: ApartmentInput, store: Store | undefined = defaultStore()): Queued[] {
  const items = [...load(store), { id: crypto.randomUUID(), at: new Date().toISOString(), body }];
  save(items, store);
  return items;
}

export function discard(id: string, store: Store | undefined = defaultStore()): Queued[] {
  const items = load(store).filter((q) => q.id !== id);
  save(items, store);
  return items;
}

/** A failed fetch (no signal) throws a TypeError; an HTTP error from the server does not. */
export const isNetworkError = (err: unknown) => err instanceof TypeError;

/**
 * Send queued apartments in order. A network failure stops the run and keeps the rest;
 * a server rejection keeps that item with its error so the owner can fix or discard it.
 */
export async function flush(send: (body: ApartmentInput) => Promise<unknown>, store: Store | undefined = defaultStore()):
    Promise<{ sent: number; remaining: Queued[] }> {
  let sent = 0;
  const kept: Queued[] = [];
  const items = load(store);
  for (let i = 0; i < items.length; i++) {
    try {
      await send(items[i].body);
      sent++;
    } catch (err) {
      if (isNetworkError(err)) {
        kept.push(...items.slice(i));
        break;
      }
      kept.push({ ...items[i], error: err instanceof Error ? err.message.slice(0, 160) : "rejected" });
    }
  }
  save(kept, store);
  return { sent, remaining: kept };
}

const COMPASS_POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

/** The nearest of the eight compass points to a heading in degrees clockwise from north. */
export function headingToCompass(degrees: number): (typeof COMPASS_POINTS)[number] {
  const d = ((degrees % 360) + 360) % 360;
  return COMPASS_POINTS[Math.round(d / 45) % 8];
}
