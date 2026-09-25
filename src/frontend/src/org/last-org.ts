/**
 * Remembers the last organization the user looked at.
 *
 * This is only a redirect hint for `/`; the organization actually in use is
 * always the one in the URL, never this value.
 */
const KEY = 'graphforge.lastOrgId'

export function readLastOrgId(): string | null {
  try {
    return window.localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function writeLastOrgId(organizationId: string): void {
  try {
    window.localStorage.setItem(KEY, organizationId)
  } catch {
    // A blocked storage just means the hint is not remembered.
  }
}

export function clearLastOrgId(): void {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // Ignore.
  }
}
