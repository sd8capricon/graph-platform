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

  /** Editable (draft/failed) only: the API returns 409 once indexing has started. */
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

  /**
   * Moves a draft/failed knowledge base to `indexing`. Returns 202 Accepted
   * with the updated `KnowledgeBaseDto` body (`apiJson` reads the body off any
   * `response.ok` status, so 202 is handled the same as 200) and a `Location`
   * header pointing at the new index job's status endpoint, which this client
   * does not yet follow. Returns 409 when the knowledge base has no files.
   */
  publish: (organizationId: string, knowledgeBaseId: string) =>
    apiJson<KnowledgeBaseDto>(`${base(organizationId)}/${knowledgeBaseId}/publish`, {
      method: 'POST',
    }),
}
