import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { organizationsApi } from '@/api/endpoints/organizations'
import type {
  CreateOrganizationRequest,
  OrganizationDto,
  SetActiveEmbeddingModelRequest,
  UpdateOrganizationRequest,
} from '@/api/types'
import { qk } from '@/queries/keys'

export function useOrganizationsQuery() {
  return useQuery({
    queryKey: qk.orgs.list(),
    queryFn: ({ signal }) => organizationsApi.list(signal),
    staleTime: 60_000,
  })
}

export function useOrganizationQuery(organizationId: string | undefined) {
  return useQuery({
    queryKey: qk.orgs.detail(organizationId ?? ''),
    queryFn: ({ signal }) => organizationsApi.get(organizationId!, signal),
    enabled: !!organizationId,
    staleTime: 60_000,
  })
}

export function useCreateOrganization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateOrganizationRequest) => organizationsApi.create(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs.list() })
      // The caller just became a member, so their membership list changed.
      void queryClient.invalidateQueries({ queryKey: qk.auth.me() })
    },
  })
}

export function useUpdateOrganization(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateOrganizationRequest) =>
      organizationsApi.update(organizationId, body),
    onSuccess: (organization: OrganizationDto) => {
      queryClient.setQueryData(qk.orgs.detail(organizationId), organization)
      void queryClient.invalidateQueries({ queryKey: qk.orgs.list() })
      // The switcher renders organization names from the membership list.
      void queryClient.invalidateQueries({ queryKey: qk.auth.me() })
    },
  })
}

export function useDeleteOrganization(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => organizationsApi.remove(organizationId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: qk.orgs.detail(organizationId) })
      void queryClient.invalidateQueries({ queryKey: qk.orgs.list() })
      void queryClient.invalidateQueries({ queryKey: qk.auth.me() })
    },
  })
}

export function useSetActiveEmbeddingModel(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: SetActiveEmbeddingModelRequest) =>
      organizationsApi.setActiveEmbeddingModel(organizationId, body),
    onSuccess: (organization: OrganizationDto) => {
      queryClient.setQueryData(qk.orgs.detail(organizationId), organization)
      // Which model can be deleted has just changed.
      void queryClient.invalidateQueries({ queryKey: qk.models.all(organizationId) })
    },
  })
}
