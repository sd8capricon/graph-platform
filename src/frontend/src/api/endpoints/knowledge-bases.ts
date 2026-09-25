import { apiJson, apiVoid } from '@/api/http'
import type {
  CreateKnowledgeBaseRequest,
  KnowledgeBaseDto,
  UpdateKnowledgeBaseRequest,
} from '@/api/types'

const base = (organizationId: string) =>
  `api/organizations/${organizationId}/knowledge-bases`

export const knowledgeBasesApi = {
  list: (organizationId: string, signal?: AbortSignal) =>
    apiJson<KnowledgeBaseDto[]>(base(organizationId), { signal }),

  get: (organizationId: string, knowledgeBaseId: string, signal?: AbortSignal) =>
    apiJson<KnowledgeBaseDto>(`${base(organizationId)}/${knowledgeBaseId}`, { signal }),

  create: (organizationId: string, body: CreateKnowledgeBaseRequest) =>
    apiJson<KnowledgeBaseDto>(base(organizationId), { method: 'POST', body }),

  /** Draft-only: the API returns 409 once indexing has started. */
  update: (
    organizationId: string,
    knowledgeBaseId: string,
    body: UpdateKnowledgeBaseRequest,
  ) =>
    apiJson<KnowledgeBaseDto>(`${base(organizationId)}/${knowledgeBaseId}`, {
      method: 'PUT',
      body,
    }),

  remove: (organizationId: string, knowledgeBaseId: string) =>
    apiVoid(`${base(organizationId)}/${knowledgeBaseId}`, { method: 'DELETE' }),

  /** Moves a draft to `indexing`. Irreversible from the UI's point of view. */
  publish: (organizationId: string, knowledgeBaseId: string) =>
    apiJson<KnowledgeBaseDto>(`${base(organizationId)}/${knowledgeBaseId}/publish`, {
      method: 'POST',
    }),
}
