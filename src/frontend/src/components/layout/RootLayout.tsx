import { Outlet } from 'react-router'

import { SrAnnouncer } from '@/components/feedback/SrAnnouncer'
import { Toaster } from '@/components/ui/sonner'

export function RootLayout() {
  return (
    <>
      {/* First focusable element on the page. */}
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Outlet />
      <Toaster richColors closeButton position="bottom-right" />
      <SrAnnouncer />
    </>
  )
}
