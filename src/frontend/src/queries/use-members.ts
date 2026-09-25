import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { membersApi } from '@/api/endpoints/members'
import type { AddMemberRequest, MemberDto, OrganizationRole } from '@/api/types'
import { qk } from '@/queries/keys'

export function useMembersQuery(organizationId: string | undefined) {
  return useQuery({
    queryKey: qk.orgs.members(organizationId ?? ''),
    queryFn: ({ signal }) => membersApi.list(organizationId!, signal),
    enabled: !!organizationId,
    staleTime: 30_000,
  })
}

export function useAddMember(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AddMemberRequest) => membersApi.add(organizationId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs.members(organizationId) })
    },
  })
}

interface UpdateRoleInput {
  userId: string
  role: OrganizationRole
  /** Demoting yourself changes your own gating, so `me` has to be refetched. */
  isSelf: boolean
}

export function useUpdateMemberRole(organizationId: string) {
  const queryClient = useQueryClient()
  const key = qk.orgs.members(organizationId)

  return useMutation({
    mutationFn: ({ userId, role }: UpdateRoleInput) =>
      membersApi.updateRole(organizationId, userId, { role }),

    // Optimistic: the role <Select> visibly snapping back on every change is
    // the one place a round-trip reads as broken.
    onMutate: async ({ userId, role }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<MemberDto[]>(key)
      if (previous) {
        queryClient.setQueryData<MemberDto[]>(
          key,
          previous.map((member) =>
            member.userId === userId ? { ...member, role } : member,
          ),
        )
      }
      return { previous }
    },

    onError: (_error, _input, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },

    onSettled: (_data, _error, input) => {
      void queryClient.invalidateQueries({ queryKey: key })
      if (input?.isSelf) void queryClient.invalidateQueries({ queryKey: qk.auth.me() })
    },
  })
}

export function useRemoveMember(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId }: { userId: string; isSelf: boolean }) =>
      membersApi.remove(organizationId, userId),
    onSuccess: (_data, input) => {
      void queryClient.invalidateQueries({ queryKey: qk.orgs.members(organizationId) })
      if (input.isSelf) void queryClient.invalidateQueries({ queryKey: qk.auth.me() })
    },
  })
}
