import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { knowledgeBasesApi } from '@/api/endpoints/knowledge-bases'
import {
  KnowledgeBaseState,
  type CreateKnowledgeBaseRequest,
  type KnowledgeBaseDto,
  type UpdateKnowledgeBaseRequest,
} from '@/api/types'
import { qk } from '@/queries/keys'

/** Poll only while something is actually in flight, so an idle list is free. */
const POLL_MS = 5_000

export function useKnowledgeBasesQuery(organizationId: string | undefined) {
  return useQuery({
    queryKey: qk.knowledgeBases.list(organizationId ?? ''),
    queryFn: ({ signal }) => knowledgeBasesApi.list(organizationId!, signal),
    enabled: !!organizationId,
    staleTime: 15_000,
    refetchInterval: (query) =>
      query.state.data?.some((kb) => kb.state === KnowledgeBaseState.Indexing)
        ? POLL_MS
        : false,
  })
}

export function useKnowledgeBaseQuery(
  organizationId: string | undefined,
  knowledgeBaseId: string | undefined,
) {
  return useQuery({
    queryKey: qk.knowledgeBases.detail(organizationId ?? '', knowledgeBaseId ?? ''),
    queryFn: ({ signal }) =>
      knowledgeBasesApi.get(organizationId!, knowledgeBaseId!, signal),
    enabled: !!organizationId && !!knowledgeBaseId,
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.state === KnowledgeBaseState.Indexing ? POLL_MS : false,
  })
}

export function useCreateKnowledgeBase(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateKnowledgeBaseRequest) =>
      knowledgeBasesApi.create(organizationId, body),
    onSuccess: (knowledgeBase: KnowledgeBaseDto) => {
      queryClient.setQueryData(
        qk.knowledgeBases.detail(organizationId, knowledgeBase.id),
        knowledgeBase,
      )
      void queryClient.invalidateQueries({
        queryKey: qk.knowledgeBases.all(organizationId),
      })
    },
  })
}

export function useUpdateKnowledgeBase(organizationId: string, knowledgeBaseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateKnowledgeBaseRequest) =>
      knowledgeBasesApi.update(organizationId, knowledgeBaseId, body),
    onSuccess: (knowledgeBase: KnowledgeBaseDto) => {
      queryClient.setQueryData(
        qk.knowledgeBases.detail(organizationId, knowledgeBaseId),
        knowledgeBase,
      )
      void queryClient.invalidateQueries({
        queryKey: qk.knowledgeBases.list(organizationId),
      })
    },
  })
}

export function useDeleteKnowledgeBase(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (knowledgeBaseId: string) =>
      knowledgeBasesApi.remove(organizationId, knowledgeBaseId),
    onSuccess: (_data, knowledgeBaseId) => {
      queryClient.removeQueries({
        queryKey: qk.knowledgeBases.detail(organizationId, knowledgeBaseId),
      })
      void queryClient.invalidateQueries({
        queryKey: qk.knowledgeBases.list(organizationId),
      })
    },
  })
}

export function usePublishKnowledgeBase(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (knowledgeBaseId: string) =>
      knowledgeBasesApi.publish(organizationId, knowledgeBaseId),
    // Not optimistic: this is a server-authoritative state machine, and rolling
    // `indexing` back to `draft` on failure would be more confusing than a wait.
    onSuccess: (knowledgeBase: KnowledgeBaseDto) => {
      queryClient.setQueryData(
        qk.knowledgeBases.detail(organizationId, knowledgeBase.id),
        knowledgeBase,
      )
      void queryClient.invalidateQueries({
        queryKey: qk.knowledgeBases.list(organizationId),
      })
    },
  })
}
