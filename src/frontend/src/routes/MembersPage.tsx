import * as React from 'react'
import { ShieldAlert, UserPlus, Users } from 'lucide-react'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { OrganizationRole, type MemberDto } from '@/api/types'
import { useAuth } from '@/auth/use-auth'
import { DataToolbar } from '@/components/data/DataToolbar'
import { ConfirmDialog } from '@/components/feedback/ConfirmDialog'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { PageHeader } from '@/components/feedback/PageHeader'
import { TableSkeleton } from '@/components/feedback/TableSkeleton'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { InviteMemberDialog } from '@/features/members/InviteMemberDialog'
import { MembersTable } from '@/features/members/MembersTable'
import { useClientCollection } from '@/hooks/use-client-collection'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { ROLE_LABELS } from '@/org/permissions'
import { useCurrentOrg } from '@/org/use-current-org'
import {
  useMembersQuery,
  useRemoveMember,
  useUpdateMemberRole,
} from '@/queries/use-members'

type RoleFilter = OrganizationRole | 'all'

export function MembersPage() {
  useDocumentTitle('Members')
  const { organizationId, canGovern } = useCurrentOrg()
  const { user } = useAuth()

  const { data, isPending, isError, error, refetch } = useMembersQuery(organizationId)
  const updateRole = useUpdateMemberRole(organizationId)
  const removeMember = useRemoveMember(organizationId)

  const [inviteOpen, setInviteOpen] = React.useState(false)
  const [removing, setRemoving] = React.useState<MemberDto | null>(null)
  const [roleFilter, setRoleFilter] = React.useState<RoleFilter>('all')

  const searchFields = React.useCallback(
    (member: MemberDto) => [member.email, member.displayName],
    [],
  )

  const filters = React.useMemo(
    () => (roleFilter === 'all' ? [] : [(member: MemberDto) => member.role === roleFilter]),
    [roleFilter],
  )

  const collection = useClientCollection({
    items: data,
    searchFields,
    filters,
    sortKey: 'email',
  })

  if (!canGovern) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Members are managed by an Organization Admin"
        description="You can see who is in this organization, but only an Organization Admin can change roles or add people."
      />
    )
  }

  return (
    <>
      <PageHeader
        title="Members"
        description="Roles are per organization and take effect on the member's next request."
        actions={
          <Button onClick={() => setInviteOpen(true)}>
            <UserPlus aria-hidden="true" />
            Add member
          </Button>
        }
      />

      {isPending ? (
        <TableSkeleton rows={5} columns={4} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No members yet"
          description="Add someone who has already created an account."
          action={
            <Button onClick={() => setInviteOpen(true)}>
              <UserPlus aria-hidden="true" />
              Add member
            </Button>
          }
        />
      ) : (
        <div className="space-y-4">
          <DataToolbar
            search={collection.search}
            onSearchChange={collection.setSearch}
            searchPlaceholder="Search by name or email…"
            searchLabel="Search members"
            matchedCount={collection.matchedCount}
            totalCount={collection.totalCount}
            noun="members"
            isFiltered={collection.isFiltered}
            onClearFilters={() => {
              collection.setSearch('')
              setRoleFilter('all')
            }}
          >
            <Select
              value={roleFilter}
              onValueChange={(value) => setRoleFilter(value as RoleFilter)}
            >
              <SelectTrigger className="w-full sm:w-52" aria-label="Filter by role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All roles</SelectItem>
                {Object.values(OrganizationRole).map((role) => (
                  <SelectItem key={role} value={role}>
                    {ROLE_LABELS[role]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </DataToolbar>

          {collection.matchedCount === 0 ? (
            <EmptyState
              title="No members match those filters"
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    collection.setSearch('')
                    setRoleFilter('all')
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <MembersTable
              members={collection.matched}
              currentUserId={user?.id}
              canGovern={canGovern}
              onRoleChange={(member, role) =>
                updateRole.mutate(
                  { userId: member.userId, role, isSelf: member.userId === user?.id },
                  {
                    onSuccess: () => toast.success('Role updated'),
                    onError: (mutationError) =>
                      toast.error(
                        isApiError(mutationError)
                          ? (mutationError.detail ?? mutationError.title)
                          : 'Could not change the role.',
                      ),
                  },
                )
              }
              onRemove={setRemoving}
            />
          )}
        </div>
      )}

      <InviteMemberDialog
        organizationId={organizationId}
        open={inviteOpen}
        onOpenChange={setInviteOpen}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove this member?"
        description="They lose access to this organization immediately. Their account itself is not deleted."
        confirmLabel="Remove"
        destructive
        pending={removeMember.isPending}
        onConfirm={() => {
          if (!removing) return
          removeMember.mutate(
            { userId: removing.userId, isSelf: removing.userId === user?.id },
            {
              onSuccess: () => {
                toast.success('Member removed')
                setRemoving(null)
              },
              onError: (mutationError) => {
                toast.error(
                  isApiError(mutationError)
                    ? (mutationError.detail ?? mutationError.title)
                    : 'Could not remove the member.',
                )
                setRemoving(null)
              },
            },
          )
        }}
      />
    </>
  )
}
