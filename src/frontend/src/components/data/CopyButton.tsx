import * as React from 'react'
import { Check, Copy } from 'lucide-react'

import { announce } from '@/components/feedback/announcer'
import { Button } from '@/components/ui/button'

interface CopyButtonProps {
  value: string
  label?: string
}

export function CopyButton({ value, label = 'identifier' }: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false)

  React.useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-7"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
          setCopied(true)
          announce(`Copied ${label} to the clipboard`)
        } catch {
          announce(`Could not copy the ${label}`)
        }
      }}
    >
      {copied ? (
        <Check className="text-emerald-600" aria-hidden="true" />
      ) : (
        <Copy aria-hidden="true" />
      )}
      <span className="sr-only">Copy {label}</span>
    </Button>
  )
}
