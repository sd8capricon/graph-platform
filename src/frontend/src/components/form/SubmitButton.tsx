import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface SubmitButtonProps {
  pending: boolean
  children: ReactNode
  pendingLabel?: string
  disabled?: boolean
  className?: string
}

export function SubmitButton({
  pending,
  children,
  pendingLabel,
  disabled,
  className,
}: SubmitButtonProps) {
  return (
    <Button type="submit" disabled={pending || disabled} className={className}>
      {pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
      {pending ? (pendingLabel ?? children) : children}
    </Button>
  )
}
