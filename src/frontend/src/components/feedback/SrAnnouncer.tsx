import * as React from 'react'

import { subscribeToAnnouncements } from '@/components/feedback/announcer'

/** Mounted once, near the root. */
export function SrAnnouncer() {
  const [message, setMessage] = React.useState('')

  React.useEffect(() => subscribeToAnnouncements(setMessage), [])

  return (
    <div aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </div>
  )
}
