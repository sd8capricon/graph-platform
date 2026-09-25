import type { ModelDto } from '@/api/types'

export function deleteReasonFor(
  model: ModelDto,
  canAuthor: boolean,
  activeEmbeddingModelId: string | null,
): string | null {
  if (!canAuthor) return 'You need the Contributor or Organization Admin role.'
  if (model.id === activeEmbeddingModelId) {
    return 'This is the organization’s active embedding model. Change it in Settings first.'
  }
  return null
}
