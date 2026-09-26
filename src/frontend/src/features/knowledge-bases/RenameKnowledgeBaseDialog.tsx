import { toast } from 'sonner'

import type { KnowledgeBaseDto } from '@/api/types'
import { KnowledgeBaseNameDialog } from '@/features/knowledge-bases/KnowledgeBaseNameDialog'
import { useUpdateKnowledgeBase } from '@/queries/use-knowledge-bases'

interface RenameKnowledgeBaseDialogProps {
  knowledgeBase: KnowledgeBaseDto
  organizationId: string
  onClose: () => void
}

/**
 * Mounted only while renaming, so `useUpdateKnowledgeBase` gets a concrete id
 * and the mutation still runs its cache invalidation.
 */
export function RenameKnowledgeBaseDialog({
  knowledgeBase,
  organizationId,
  onClose,
}: RenameKnowledgeBaseDialogProps) {
  const updateKnowledgeBase = useUpdateKnowledgeBase(organizationId, knowledgeBase.id)

  return (
    <KnowledgeBaseNameDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title="Rename knowledge base"
      description="Only a draft or failed knowledge base can be renamed."
      submitLabel="Save"
      initialName={knowledgeBase.name}
      onSubmit={async (name) => {
        await updateKnowledgeBase.mutateAsync({ name })
        toast.success('Renamed')
        onClose()
      }}
    />
  )
}
