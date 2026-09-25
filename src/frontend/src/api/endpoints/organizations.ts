import { apiJson, apiVoid } from '@/api/http'
import type {
  CreateOrganizationRequest,
  OrganizationDto,
  SetActiveEmbeddingModelRequest,
  UpdateOrganizationRequest,
} from '@/api/types'

const base = 'api/organizations'

export const organizationsApi = {
  /** Returns only the organizations the caller belongs to, ordered by name. */
  list: (signal?: AbortSignal) => apiJson<OrganizationDto[]>(base, { signal }),

  get: (organizationId: string, signal?: AbortSignal) =>
    apiJson<OrganizationDto>(`${base}/${organizationId}`, { signal }),

  create: (body: CreateOrganizationRequest) =>
    apiJson<OrganizationDto>(base, { method: 'POST', body }),

  update: (organizationId: string, body: UpdateOrganizationRequest) =>
    apiJson<OrganizationDto>(`${base}/${organizationId}`, { method: 'PUT', body }),

  remove: (organizationId: string) =>
    apiVoid(`${base}/${organizationId}`, { method: 'DELETE' }),

  setActiveEmbeddingModel: (
    organizationId: string,
    body: SetActiveEmbeddingModelRequest,
  ) =>
    apiJson<OrganizationDto>(`${base}/${organizationId}/embedding-model`, {
      method: 'PUT',
      body,
    }),
}
