import * as React from 'react'
import { Outlet, useLocation } from 'react-router'

import { Breadcrumbs } from '@/components/layout/Breadcrumbs'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { UserMenu } from '@/components/layout/UserMenu'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'

/**
 * The authenticated chrome: sidebar, topbar and the main region.
 *
 * React Router does not move focus on navigation, so a keyboard user would be
 * dropped back at the browser chrome after every link. Focusing `<main>` (which
 * is why it carries `tabIndex={-1}`) on each pathname change fixes that.
 */
export function AppShell() {
  const location = useLocation()
  const mainRef = React.useRef<HTMLElement>(null)
  const isFirstRender = React.useRef(true)

  React.useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [location.pathname])

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 h-4" />
          <div className="min-w-0 flex-1">
            <Breadcrumbs />
          </div>
          <ThemeToggle />
          <UserMenu />
        </header>

        <main
          id="main"
          ref={mainRef}
          tabIndex={-1}
          className="flex-1 p-4 outline-none md:p-6 lg:p-8"
        >
          <div className="mx-auto w-full max-w-7xl space-y-6">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
