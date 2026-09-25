import { Database, MoreVertical, Pencil, Trash2 } from 'lucide-react'
import { Link } from 'react-router'

import { KnowledgeBaseState, type KnowledgeBaseDto } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { KbStateBadge } from '@/features/knowledge-bases/KbStateBadge'
import { formatDateTime, formatRelativeTime } from '@/lib/format'

interface KnowledgeBaseTableProps {
  items: KnowledgeBaseDto[]
  organizationId: string
  canAuthor: boolean
  onRename: (knowledgeBase: KnowledgeBaseDto) => void
  onDelete: (knowledgeBase: KnowledgeBaseDto) => void
}

const DRAFT_ONLY = 'Only a draft knowledge base can be changed.'
const NEEDS_ROLE = 'You need the Contributor or Organization Admin role.'

function unavailableReason(
  canAuthor: boolean,
  state: KnowledgeBaseState,
): string | null {
  if (!canAuthor) return NEEDS_ROLE
  if (state !== KnowledgeBaseState.Draft) return DRAFT_ONLY
  return null
}

export function KnowledgeBaseTable({
  items,
  organizationId,
  canAuthor,
  onRename,
  onDelete,
}: KnowledgeBaseTableProps) {
  return (
    <>
      {/* Desktop and tablet: a real table. */}
      <div className="hidden rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>State</TableHead>
              <TableHead className="hidden lg:table-cell">Files</TableHead>
              <TableHead className="hidden lg:table-cell">Updated</TableHead>
              <TableHead className="w-12">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((knowledgeBase) => {
              const reason = unavailableReason(canAuthor, knowledgeBase.state)
              return (
                <TableRow key={knowledgeBase.id}>
                  <TableCell className="font-medium">
                    <Link
                      to={`/orgs/${organizationId}/knowledge-bases/${knowledgeBase.id}`}
                      className="underline-offset-4 hover:underline"
                    >
                      {knowledgeBase.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <KbStateBadge state={knowledgeBase.state} />
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {knowledgeBase.files.length}
                  </TableCell>
                  <TableCell
                    className="hidden lg:table-cell"
                    title={formatDateTime(knowledgeBase.updatedAtUtc)}
                  >
                    {formatRelativeTime(knowledgeBase.updatedAtUtc)}
                  </TableCell>
                  <TableCell>
                    <RowActions
                      knowledgeBase={knowledgeBase}
                      reason={reason}
                      onRename={onRename}
                      onDelete={onDelete}
                    />
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {/* Mobile: stacked cards, rather than a seven-column sideways scroll. */}
      <ul className="space-y-3 md:hidden">
        {items.map((knowledgeBase) => {
          const reason = unavailableReason(canAuthor, knowledgeBase.state)
          return (
            <li
              key={knowledgeBase.id}
              className="flex items-start gap-3 rounded-lg border p-4"
            >
              <Database
                className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1 space-y-2">
                <Link
                  to={`/orgs/${organizationId}/knowledge-bases/${knowledgeBase.id}`}
                  className="block truncate font-medium underline-offset-4 hover:underline"
                >
                  {knowledgeBase.name}
                </Link>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <KbStateBadge state={knowledgeBase.state} />
                  <span>
                    {knowledgeBase.files.length}{' '}
                    {knowledgeBase.files.length === 1 ? 'file' : 'files'}
                  </span>
                  <span>· {formatRelativeTime(knowledgeBase.updatedAtUtc)}</span>
                </div>
              </div>
              <RowActions
                knowledgeBase={knowledgeBase}
                reason={reason}
                onRename={onRename}
                onDelete={onDelete}
              />
            </li>
          )
        })}
      </ul>
    </>
  )
}

interface RowActionsProps {
  knowledgeBase: KnowledgeBaseDto
  reason: string | null
  onRename: (knowledgeBase: KnowledgeBaseDto) => void
  onDelete: (knowledgeBase: KnowledgeBaseDto) => void
}

function RowActions({ knowledgeBase, reason, onRename, onDelete }: RowActionsProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8">
          <MoreVertical aria-hidden="true" />
          <span className="sr-only">Actions for {knowledgeBase.name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          disabled={!!reason}
          onSelect={() => onRename(knowledgeBase)}
          title={reason ?? undefined}
        >
          <Pencil aria-hidden="true" />
          Rename
        </DropdownMenuItem>
        <DropdownMenuItem
          variant="destructive"
          disabled={!!reason}
          onSelect={() => onDelete(knowledgeBase)}
          title={reason ?? undefined}
        >
          <Trash2 aria-hidden="true" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
