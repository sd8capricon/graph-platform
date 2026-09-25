import { KeyRound, MoreVertical, ShieldCheck, SlidersHorizontal, Star, Trash2 } from 'lucide-react'
import { Link } from 'react-router'

import { AuthMode, type ModelDto } from '@/api/types'
import { Badge } from '@/components/ui/badge'
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
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatRelativeTime, humanizeEnum } from '@/lib/format'

interface ModelsTableProps {
  models: ModelDto[]
  organizationId: string
  activeEmbeddingModelId: string | null
  canAuthor: boolean
  onDelete: (model: ModelDto) => void
}

function deleteReasonFor(
  model: ModelDto,
  canAuthor: boolean,
  activeEmbeddingModelId: string | null,
): string | null {
  if (!canAuthor) return 'You need the Contributor or Organization Admin role.'
  if (model.id === activeEmbeddingModelId) {
    return 'This is the organization’s active embedding model. Change it in Settings first.'
  }
  return null
}

export function ModelsTable({
  models,
  organizationId,
  activeEmbeddingModelId,
  canAuthor,
  onDelete,
}: ModelsTableProps) {
  const authBadge = (model: ModelDto) =>
    model.authMode === AuthMode.ApiKey ? (
      <Badge variant={model.hasApiKey ? 'secondary' : 'destructive'} className="gap-1">
        <KeyRound aria-hidden="true" />
        {model.hasApiKey ? 'API key' : 'No key stored'}
      </Badge>
    ) : (
      <Badge variant="secondary" className="gap-1">
        <ShieldCheck aria-hidden="true" />
        Managed identity
      </Badge>
    )

  const activeMarker = (model: ModelDto) =>
    model.id === activeEmbeddingModelId ? (
      <Tooltip>
        <TooltipTrigger asChild>
          <Star className="size-4 fill-amber-400 text-amber-500" aria-hidden="true" />
        </TooltipTrigger>
        <TooltipContent>Active embedding model</TooltipContent>
      </Tooltip>
    ) : null

  const rowActions = (model: ModelDto) => {
    const reason = deleteReasonFor(model, canAuthor, activeEmbeddingModelId)
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8">
            <MoreVertical aria-hidden="true" />
            <span className="sr-only">Actions for {model.displayName}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <Link to={`/orgs/${organizationId}/models/${model.id}`}>
              <SlidersHorizontal aria-hidden="true" />
              Open
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            disabled={!!reason}
            title={reason ?? undefined}
            onSelect={() => onDelete(model)}
          >
            <Trash2 aria-hidden="true" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  return (
    <>
      <div className="hidden rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Display name</TableHead>
              <TableHead className="hidden lg:table-cell">Model</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead className="hidden lg:table-cell">Capabilities</TableHead>
              <TableHead>Auth</TableHead>
              <TableHead className="hidden lg:table-cell">Updated</TableHead>
              <TableHead className="w-12">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((model) => (
              <TableRow key={model.id}>
                <TableCell className="font-medium">
                  <span className="flex items-center gap-2">
                    <Link
                      to={`/orgs/${organizationId}/models/${model.id}`}
                      className="underline-offset-4 hover:underline"
                    >
                      {model.displayName}
                    </Link>
                    {activeMarker(model)}
                  </span>
                </TableCell>
                <TableCell className="hidden font-mono text-xs lg:table-cell">
                  {model.name}
                </TableCell>
                <TableCell>{model.provider}</TableCell>
                <TableCell className="hidden lg:table-cell">
                  <span className="flex flex-wrap gap-1">
                    {model.type.length === 0 ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      model.type.map((capability) => (
                        <Badge key={capability} variant="outline">
                          {humanizeEnum(capability)}
                        </Badge>
                      ))
                    )}
                  </span>
                </TableCell>
                <TableCell>{authBadge(model)}</TableCell>
                <TableCell className="hidden lg:table-cell">
                  {formatRelativeTime(model.updatedAtUtc)}
                </TableCell>
                <TableCell>{rowActions(model)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="space-y-3 md:hidden">
        {models.map((model) => (
          <li key={model.id} className="flex items-start gap-3 rounded-lg border p-4">
            <div className="min-w-0 flex-1 space-y-2">
              <span className="flex items-center gap-2">
                <Link
                  to={`/orgs/${organizationId}/models/${model.id}`}
                  className="truncate font-medium underline-offset-4 hover:underline"
                >
                  {model.displayName}
                </Link>
                {activeMarker(model)}
              </span>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {model.provider}/{model.name}
              </p>
              <div className="flex flex-wrap items-center gap-1">
                {model.type.map((capability) => (
                  <Badge key={capability} variant="outline">
                    {humanizeEnum(capability)}
                  </Badge>
                ))}
                {authBadge(model)}
              </div>
            </div>
            {rowActions(model)}
          </li>
        ))}
      </ul>
    </>
  )
}
