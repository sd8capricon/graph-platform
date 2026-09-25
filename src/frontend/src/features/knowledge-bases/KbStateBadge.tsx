import { CheckCircle2, FileEdit, Loader2 } from 'lucide-react'

import { KnowledgeBaseState } from '@/api/types'
import { Badge } from '@/components/ui/badge'

const PRESENTATION = {
  [KnowledgeBaseState.Draft]: {
    label: 'Draft',
    icon: FileEdit,
    variant: 'secondary' as const,
    spin: false,
  },
  [KnowledgeBaseState.Indexing]: {
    label: 'Indexing',
    icon: Loader2,
    variant: 'outline' as const,
    spin: true,
  },
  [KnowledgeBaseState.Published]: {
    label: 'Published',
    icon: CheckCircle2,
    variant: 'default' as const,
    spin: false,
  },
}

/** Colour is always paired with an icon and a word, never used on its own. */
export function KbStateBadge({ state }: { state: KnowledgeBaseState }) {
  const { label, icon: Icon, variant, spin } = PRESENTATION[state]

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
