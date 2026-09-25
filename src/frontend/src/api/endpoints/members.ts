import { apiJson, apiVoid } from '@/api/http'
import type { AddMemberRequest, MemberDto, UpdateMemberRoleRequest } from '@/api/types'

const base = (organizationId: string) => `api/organizations/${organizationId}/members`

export const membersApi = {
  /** Any member may read the roster; ordered by email. */
  list: (organizationId: string, signal?: AbortSignal) =>
    apiJson<MemberDto[]>(base(organizationId), { signal }),

  /** The target must already have signed up, otherwise the API returns 404. */
  add: (organizationId: string, body: AddMemberRequest) =>
    apiJson<MemberDto>(base(organizationId), { method: 'POST', body }),

  updateRole: (organizationId: string, userId: string, body: UpdateMemberRoleRequest) =>
    apiJson<MemberDto>(`${base(organizationId)}/${userId}`, { method: 'PUT', body }),

  remove: (organizationId: string, userId: string) =>
    apiVoid(`${base(organizationId)}/${userId}`, { method: 'DELETE' }),
}
