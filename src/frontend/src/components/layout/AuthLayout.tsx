import type { ReactNode } from 'react'

import { Brand } from '@/components/layout/Brand'

interface AuthLayoutProps {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}

export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 p-4 sm:p-6">
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
