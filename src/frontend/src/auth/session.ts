import type { StoredSession } from '@/api/token-store'

/** Log out slightly early so a request is never sent with a just-expired token. */
export const EXPIRY_GRACE_MS = 30_000
/** Warn the user with enough time to finish what they are doing. */
export const EXPIRY_WARNING_MS = 5 * 60_000

export function millisecondsUntilExpiry(session: StoredSession): number {
  return new Date(session.expiresAtUtc).getTime() - Date.now()
}

export function isExpired(session: StoredSession): boolean {
  const remaining = millisecondsUntilExpiry(session)
  return !Number.isFinite(remaining) || remaining <= EXPIRY_GRACE_MS
}
