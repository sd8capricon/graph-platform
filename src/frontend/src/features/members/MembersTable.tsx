import { Trash2, UserCog } from 'lucide-react'

import { OrganizationRole, type MemberDto } from '@/api/types'
import { ActionTooltip } from '@/components/data/ActionTooltip'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { ROLE_LABELS } from '@/org/permissions'

const LAST_ADMIN = 'An organization must keep at least one Organization Admin.'

interface MembersTableProps {
  members: MemberDto[]
  currentUserId: string | undefined
  canGovern: boolean
  onRoleChange: (member: MemberDto, role: OrganizationRole) => void
  onRemove: (member: MemberDto) => void
}

function initials(value: string): string {
  const parts = value.trim().split(/[\s@._-]+/).filter(Boolean)
  return (parts[0]?.[0] ?? '?').concat(parts[1]?.[0] ?? '').toUpperCase()
}

export function MembersTable({
  members,
  currentUserId,
  canGovern,
  onRoleChange,
  onRemove,
}: MembersTableProps) {
  const adminCount = members.filter(
    (member) => member.role === OrganizationRole.OrganizationAdmin,
  ).length

  // Mirrors the server's 409: the last admin can be neither demoted nor removed.
  const lockReason = (member: MemberDto): string | null => {
    if (!canGovern) return 'Only an Organization Admin can manage members.'
    if (member.role === OrganizationRole.OrganizationAdmin && adminCount === 1) {
      return LAST_ADMIN
    }
    return null
  }

  const display = (member: MemberDto) =>
    member.displayName?.trim() || member.email || member.userId

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Member</TableHead>
            <TableHead>Role</TableHead>
            <TableHead className="hidden lg:table-cell">Joined</TableHead>
            <TableHead className="w-12">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((member) => {
            const reason = lockReason(member)
            const isSelf = member.userId === currentUserId
            return (
              <TableRow key={member.userId}>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <Avatar className="size-8">
                      <AvatarFallback className="text-xs">
                        {initials(display(member))}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0">
                      <p className="truncate font-medium">
                        {display(member)}
                        {isSelf ? (
                          <span className="ml-1 text-xs text-muted-foreground">(you)</span>
                        ) : null}
                      </p>
                      {member.email && member.email !== display(member) ? (
                        <p className="truncate text-xs text-muted-foreground">
                          {member.email}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </TableCell>

                <TableCell>
                  {canGovern ? (
                    <ActionTooltip reason={reason}>
                      <Select
                        value={member.role}
                        disabled={!!reason}
                        onValueChange={(value) =>
                          onRoleChange(member, value as OrganizationRole)
                        }
                      >
                        <SelectTrigger
                          size="sm"
                          className="w-48"
                          aria-label={`Role for ${display(member)}`}
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {Object.values(OrganizationRole).map((role) => (
                            <SelectItem key={role} value={role}>
                              {ROLE_LABELS[role]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </ActionTooltip>
                  ) : (
                    <Badge variant="secondary" className="gap-1">
                      <UserCog aria-hidden="true" />
                      {ROLE_LABELS[member.role]}
                    </Badge>
                  )}
                </TableCell>

                <TableCell className="hidden lg:table-cell">
                  {formatDate(member.joinedAtUtc)}
                </TableCell>

                <TableCell>
                  {canGovern ? (
                    <ActionTooltip reason={reason}>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-destructive hover:text-destructive"
                        disabled={!!reason}
                        aria-disabled={!!reason}
                        onClick={() => onRemove(member)}
                      >
                        <Trash2 aria-hidden="true" />
                        <span className="sr-only">Remove {display(member)}</span>
                      </Button>
                    </ActionTooltip>
                  ) : null}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
