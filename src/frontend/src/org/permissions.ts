import { KnowledgeBaseState, OrganizationRole } from '@/api/types'

/**
 * Mirrors the server's `OrganizationAccessService`. The names match deliberately
 * so drift between the two is visible in review.
 */
export function canGovern(role: OrganizationRole | null | undefined): boolean {
  return role === OrganizationRole.OrganizationAdmin
}

export function canAuthor(role: OrganizationRole | null | undefined): boolean {
  return (
    role === OrganizationRole.OrganizationAdmin || role === OrganizationRole.Contributor
  )
}

export function canRead(role: OrganizationRole | null | undefined): boolean {
  return role != null
}

/**
 * A knowledge base can be updated/deleted/have files uploaded or deleted while
 * it is `draft` or `failed` — a failed indexing run is retried by editing and
 * republishing, not by starting over. Mirrors the API's editable rule.
 */
export function isEditableKnowledgeBaseState(state: KnowledgeBaseState): boolean {
  return state === KnowledgeBaseState.Draft || state === KnowledgeBaseState.Failed
}

export const ROLE_LABELS: Record<OrganizationRole, string> = {
  [OrganizationRole.OrganizationAdmin]: 'Organization admin',
  [OrganizationRole.Contributor]: 'Contributor',
  [OrganizationRole.User]: 'User',
}

export const ROLE_DESCRIPTIONS: Record<OrganizationRole, string> = {
  [OrganizationRole.OrganizationAdmin]:
    'Full access, including members and the active embedding model.',
  [OrganizationRole.Contributor]: 'Can create and manage models and knowledge bases.',
  [OrganizationRole.User]: 'Read-only access to this organization.',
}
