import type { ReactNode } from 'react'

import { Brand } from '@/components/layout/Brand'
import { ThemeToggle } from '@/components/layout/ThemeToggle'

interface AuthLayoutProps {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}

export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="relative flex min-h-svh flex-col items-center justify-center gap-6 p-4 sm:p-6">
      {/*
        These pages have no topbar, so the toggle is pinned to the corner rather
        than sitting left of the avatar as it does in `AppShell`. It is first in
        DOM order (not just visually positioned) so tab order reaches it before
        the credential fields, and it is outside the centred card so it does not
        read as part of the form.
      */}
      <div className="absolute top-4 right-4 sm:top-6 sm:right-6">
        <ThemeToggle />
      </div>
      <Brand className="text-lg" />
      <div className="w-full max-w-sm space-y-6 rounded-lg border bg-card p-6 shadow-xs">
        <div className="space-y-1 text-center">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {description ? (
            <p className="text-sm text-muted-foreground text-pretty">{description}</p>
          ) : null}
        </div>
        {children}
      </div>
      {footer ? <p className="text-sm text-muted-foreground">{footer}</p> : null}
    </div>
  )
}
