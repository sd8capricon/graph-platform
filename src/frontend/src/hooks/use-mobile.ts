import * as React from 'react'

const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

/**
 * Subscribes to a media query through `useSyncExternalStore`.
 *
 * The shadcn-generated version set state inside an effect, which the React
 * Compiler lint rules reject as a cascading render. `useSyncExternalStore` is
 * the primitive built for reading an external, changing value, and it also
 * gives a correct value on the very first render instead of a frame of `false`.
 */
function subscribe(onChange: () => void) {
  const query = window.matchMedia(QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

export function useIsMobile() {
  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    // Server/prerender fallback: assume desktop so the sidebar is not a sheet.
    () => false,
  )
}
