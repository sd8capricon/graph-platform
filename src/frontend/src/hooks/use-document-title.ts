import * as React from 'react'

import { env } from '@/app/env'
import { announce } from '@/components/feedback/announcer'

/**
 * Sets the tab title and announces the page.
 *
 * A single-page app changes neither on navigation by itself, so without this a
 * screen-reader user gets no indication that the page changed.
 */
export function useDocumentTitle(title: string | undefined): void {
  React.useEffect(() => {
    if (!title) return
    document.title = `${title} · ${env.appName}`
    announce(title)
    return () => {
      document.title = env.appName
    }
  }, [title])
}
