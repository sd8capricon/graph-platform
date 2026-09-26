import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { filesApi } from '@/api/endpoints/files'
import { FileStatus, type FileDto } from '@/api/types'
import { saveBlob } from '@/lib/download'
import { qk } from '@/queries/keys'

const POLL_MS = 5_000

const IN_FLIGHT: FileStatus[] = [FileStatus.Processing]

export function useFilesQuery(
  organizationId: string | undefined,
  knowledgeBaseId: string | undefined,
  /** Seeded from the knowledge base detail response, which already embeds files. */
  initialData?: FileDto[],
) {
  return useQuery({
    queryKey: qk.knowledgeBases.files(organizationId ?? '', knowledgeBaseId ?? ''),
    queryFn: ({ signal }) => filesApi.list(organizationId!, knowledgeBaseId!, signal),
    enabled: !!organizationId && !!knowledgeBaseId,
    initialData,
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.some((file) => IN_FLIGHT.includes(file.status))
        ? POLL_MS
        : false,
  })
}

/** Both the files list and the KB detail change, since the DTO embeds files. */
function useFileInvalidation(organizationId: string, knowledgeBaseId: string) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({
      queryKey: qk.knowledgeBases.files(organizationId, knowledgeBaseId),
    })
    void queryClient.invalidateQueries({
      queryKey: qk.knowledgeBases.detail(organizationId, knowledgeBaseId),
    })
    void queryClient.invalidateQueries({
      queryKey: qk.knowledgeBases.list(organizationId),
    })
  }
}

export interface UploadInput {
  file: File
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

export function useUploadFile(organizationId: string, knowledgeBaseId: string) {
  const invalidate = useFileInvalidation(organizationId, knowledgeBaseId)
  return useMutation({
    mutationFn: ({ file, onProgress, signal }: UploadInput) =>
      filesApi.upload(organizationId, knowledgeBaseId, file, { onProgress, signal }),
    onSuccess: invalidate,
  })
}

export function useDeleteFile(organizationId: string, knowledgeBaseId: string) {
  const queryClient = useQueryClient()
  const invalidate = useFileInvalidation(organizationId, knowledgeBaseId)
  const key = qk.knowledgeBases.files(organizationId, knowledgeBaseId)

  return useMutation({
    mutationFn: (fileId: string) =>
      filesApi.remove(organizationId, knowledgeBaseId, fileId),

    // Optimistic: removing a row is unambiguous and the rollback is cheap.
    onMutate: async (fileId) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<FileDto[]>(key)
      if (previous) {
        queryClient.setQueryData<FileDto[]>(
          key,
          previous.filter((file) => file.id !== fileId),
        )
      }
      return { previous }
    },

    onError: (_error, _fileId, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },

    onSettled: invalidate,
  })
}

export function useDownloadFile(organizationId: string, knowledgeBaseId: string) {
  return useMutation({
    mutationFn: async (file: FileDto) => {
      const { blob, fileName } = await filesApi.download(
        organizationId,
        knowledgeBaseId,
        file.id,
      )
      // The cached name is authoritative; the header is only a fallback.
      saveBlob(blob, file.fileName || fileName || 'download')
    },
  })
}
