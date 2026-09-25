/**
 * A single polite live region, shared by the whole app.
 *
 * Toasts announce themselves, but non-toast status changes — a filtered result
 * count, a finished upload, a page change — have no natural announcement. This
 * is the one place those are spoken, so screen-reader users are not left
 * guessing whether anything happened.
 */
type Listener = (message: string) => void

const listeners = new Set<Listener>()

export function announce(message: string): void {
  for (const listener of listeners) listener(message)
}

export function subscribeToAnnouncements(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
