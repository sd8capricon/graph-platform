import { AlertCircle, Check, CheckCircle2, Loader2 } from 'lucide-react'

import { FileStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'

const PRESENTATION = {
  [FileStatus.Uploaded]: {
    label: 'Uploaded',
    icon: Check,
    variant: 'secondary' as const,
    spin: false,
  },
  [FileStatus.Processing]: {
    label: 'Processing',
    icon: Loader2,
    variant: 'outline' as const,
    spin: true,
  },
  [FileStatus.Processed]: {
    label: 'Processed',
    icon: CheckCircle2,
    variant: 'default' as const,
    spin: false,
  },
  [FileStatus.Failed]: {
    label: 'Failed',
    icon: AlertCircle,
    variant: 'destructive' as const,
    spin: false,
  },
}

export function FileStatusBadge({ status }: { status: FileStatus }) {
  const { label, icon: Icon, variant, spin } = PRESENTATION[status]

  return (
    <Badge variant={variant} className="gap-1">
      <Icon
        className={spin ? 'animate-spin motion-reduce:animate-none' : undefined}
        aria-hidden="true"
      />
      {label}
    </Badge>
  )
}
