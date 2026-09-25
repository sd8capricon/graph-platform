import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { modelsApi } from '@/api/endpoints/models'
import type { CreateModelRequest, ModelDto, UpdateModelRequest } from '@/api/types'
import { qk } from '@/queries/keys'

export function useModelsQuery(organizationId: string | undefined) {
  return useQuery({
    queryKey: qk.models.list(organizationId ?? ''),
    queryFn: ({ signal }) => modelsApi.list(organizationId!, signal),
    enabled: !!organizationId,
    staleTime: 60_000,
  })
}

export function useModelQuery(
  organizationId: string | undefined,
  modelId: string | undefined,
) {
  return useQuery({
    queryKey: qk.models.detail(organizationId ?? '', modelId ?? ''),
    queryFn: ({ signal }) => modelsApi.get(organizationId!, modelId!, signal),
    enabled: !!organizationId && !!modelId,
    staleTime: 60_000,
  })
}

export function useCreateModel(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateModelRequest) => modelsApi.create(organizationId, body),
    onSuccess: (model: ModelDto) => {
      queryClient.setQueryData(qk.models.detail(organizationId, model.id), model)
      void queryClient.invalidateQueries({ queryKey: qk.models.all(organizationId) })
    },
  })
}

export function useUpdateModel(organizationId: string, modelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateModelRequest) =>
      modelsApi.update(organizationId, modelId, body),
    onSuccess: (model: ModelDto) => {
      queryClient.setQueryData(qk.models.detail(organizationId, modelId), model)
      void queryClient.invalidateQueries({ queryKey: qk.models.list(organizationId) })
    },
  })
}

export function useDeleteModel(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (modelId: string) => modelsApi.remove(organizationId, modelId),
    onSuccess: (_data, modelId) => {
      queryClient.removeQueries({ queryKey: qk.models.detail(organizationId, modelId) })
      void queryClient.invalidateQueries({ queryKey: qk.models.list(organizationId) })
      // The server clears `activeEmbeddingModelId` when that model is removed.
      void queryClient.invalidateQueries({ queryKey: qk.orgs.detail(organizationId) })
    },
  })
}
