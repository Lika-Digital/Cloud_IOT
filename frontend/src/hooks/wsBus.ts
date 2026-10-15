/**
 * Every message the one `/ws` connection receives, offered to whoever listens (block 4,
 * 2026-10-15). useWebSocket owns the connection and the global store; a screen that needs the
 * raw events (the marina dashboard's live figures) subscribes here instead of opening a second
 * socket or growing the store.
 */
export interface WsMessage {
  event: string
  data: Record<string, unknown>
}

type Listener = (msg: WsMessage) => void
const listeners = new Set<Listener>()

/** Returns the unsubscribe function. */
export function onWsMessage(fn: Listener): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function emitWsMessage(msg: WsMessage): void {
  for (const fn of listeners) {
    try { fn(msg) } catch { /* one listener's fault must not stop the others */ }
  }
}
