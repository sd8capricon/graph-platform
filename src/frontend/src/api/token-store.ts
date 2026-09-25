/**
 * Persisted session token, deliberately framework-free.
 *
 * `http.ts` reads this synchronously on every request, so it must not depend on
 * React. It lives in `localStorage` because the API issues no refresh token and
 * sets no cookie: an in-memory token would sign the user out on every reload and
 * in every new tab, and in a SPA it is no less exposed to XSS than a stored one.
 */
const STORAGE_KEY = 'graphforge.session'

export interface StoredSession {
  accessToken: string
  /** ISO-8601 instant at which `accessToken` stops being accepted. */
  expiresAtUtc: string
  userId: string
}

type Listener = (session: StoredSession | null) => void

const listeners = new Set<Listener>()
let cached: StoredSession | null | undefined

function read(): StoredSession | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<StoredSession>
    if (!parsed.accessToken || !parsed.expiresAtUtc || !parsed.userId) return null
    return parsed as StoredSession
  } catch {
    // Unparseable or storage blocked: behave as signed out rather than crashing.
    return null
  }
}

function emit(session: StoredSession | null) {
  cached = session
  for (const listener of listeners) listener(session)
}

export const tokenStore = {
  get(): StoredSession | null {
    if (cached === undefined) cached = read()
    return cached
  },

  set(session: StoredSession): void {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    } catch {
      // Private-mode storage failure still leaves the in-memory value usable.
    }
    emit(session)
  },

  clear(): void {
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Ignore: the in-memory clear below is what the app actually reads.
    }
    emit(null)
  },

  subscribe(listener: Listener): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}

// Signing out in one tab signs out the others.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== null && event.key !== STORAGE_KEY) return
    emit(read())
  })
}
