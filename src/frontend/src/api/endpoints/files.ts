import { apiBlob, apiJson, apiUpload, apiVoid, type UploadOptions } from '@/api/http'
import type { FileDto } from '@/api/types'

const base = (organizationId: string, knowledgeBaseId: string) =>
  `api/organizations/${organizationId}/knowledge-bases/${knowledgeBaseId}/files`

export const filesApi = {
  /** Oldest first, matching the API's ordering. */
  list: (organizationId: string, knowledgeBaseId: string, signal?: AbortSignal) =>
    apiJson<FileDto[]>(base(organizationId, knowledgeBaseId), { signal }),

  get: (
    organizationId: string,
    knowledgeBaseId: string,
    fileId: string,
    signal?: AbortSignal,
  ) => apiJson<FileDto>(`${base(organizationId, knowledgeBaseId)}/${fileId}`, { signal }),

  /** Draft-only and contributor+; one file per request. */
  upload: (
    organizationId: string,
    knowledgeBaseId: string,
    file: File,
    options?: UploadOptions,
  ) => apiUpload<FileDto>(base(organizationId, knowledgeBaseId), file, options),

  download: (organizationId: string, knowledgeBaseId: string, fileId: string) =>
    apiBlob(`${base(organizationId, knowledgeBaseId)}/${fileId}/content`),

  remove: (organizationId: string, knowledgeBaseId: string, fileId: string) =>
    apiVoid(`${base(organizationId, knowledgeBaseId)}/${fileId}`, { method: 'DELETE' }),
}
