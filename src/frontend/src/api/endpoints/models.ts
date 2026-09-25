import { apiJson, apiVoid } from '@/api/http'
import type { CreateModelRequest, ModelDto, UpdateModelRequest } from '@/api/types'

const base = (organizationId: string) => `api/organizations/${organizationId}/models`

export const modelsApi = {
  list: (organizationId: string, signal?: AbortSignal) =>
    apiJson<ModelDto[]>(base(organizationId), { signal }),

  get: (organizationId: string, modelId: string, signal?: AbortSignal) =>
    apiJson<ModelDto>(`${base(organizationId)}/${modelId}`, { signal }),

  /** `body.id` is caller-assigned and required: the API never generates one. */
  create: (organizationId: string, body: CreateModelRequest) =>
    apiJson<ModelDto>(base(organizationId), { method: 'POST', body }),

  /** A full replacement: an omitted `apiKey` clears the stored key. */
  update: (organizationId: string, modelId: string, body: UpdateModelRequest) =>
    apiJson<ModelDto>(`${base(organizationId)}/${modelId}`, { method: 'PUT', body }),

  /** Returns 409 when the model is the organization's active embedding model. */
  remove: (organizationId: string, modelId: string) =>
    apiVoid(`${base(organizationId)}/${modelId}`, { method: 'DELETE' }),
}
