import { Download, FileText, Loader2, Trash2 } from 'lucide-react'

import type { FileDto } from '@/api/types'
import { ActionTooltip } from '@/components/data/ActionTooltip'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FileStatusBadge } from '@/features/knowledge-bases/FileStatusBadge'
import { formatBytes, formatDateTime, formatRelativeTime } from '@/lib/format'

interface FilesTableProps {
  files: FileDto[]
  deleteReason: string | null
  downloadingId: string | null
  deletingId: string | null
  onDownload: (file: FileDto) => void
  onDelete: (file: FileDto) => void
}

export function FilesTable({
  files,
  deleteReason,
  downloadingId,
  deletingId,
  onDownload,
  onDelete,
}: FilesTableProps) {
  const actions = (file: FileDto) => (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="ghost"
        size="icon"
        className="size-8"
        disabled={downloadingId === file.id}
        onClick={() => onDownload(file)}
      >
        {downloadingId === file.id ? (
          <Loader2 className="animate-spin" aria-hidden="true" />
        ) : (
          <Download aria-hidden="true" />
        )}
        <span className="sr-only">Download {file.fileName}</span>
      </Button>

      <ActionTooltip reason={deleteReason}>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-destructive hover:text-destructive"
          disabled={!!deleteReason || deletingId === file.id}
          aria-disabled={!!deleteReason}
          onClick={() => onDelete(file)}
        >
          {deletingId === file.id ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <Trash2 aria-hidden="true" />
          )}
          <span className="sr-only">Delete {file.fileName}</span>
        </Button>
      </ActionTooltip>
    </div>
  )

  return (
    <>
      <div className="hidden rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead className="hidden lg:table-cell">Type</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="hidden lg:table-cell">Uploaded</TableHead>
              <TableHead className="w-24 text-right">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((file) => (
              <TableRow key={file.id}>
                <TableCell className="max-w-64 truncate font-medium">
                  {file.fileName}
                </TableCell>
                <TableCell className="hidden max-w-40 truncate text-muted-foreground lg:table-cell">
                  {file.contentType}
                </TableCell>
                <TableCell>{formatBytes(file.size)}</TableCell>
                <TableCell>
                  <FileStatusBadge status={file.status} />
                </TableCell>
                <TableCell
                  className="hidden lg:table-cell"
                  title={formatDateTime(file.createdAtUtc)}
                >
                  {formatRelativeTime(file.createdAtUtc)}
                </TableCell>
                <TableCell className="text-right">{actions(file)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="space-y-3 md:hidden">
        {files.map((file) => (
          <li key={file.id} className="flex items-start gap-3 rounded-lg border p-4">
            <FileText
              className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1 space-y-2">
              <p className="truncate font-medium">{file.fileName}</p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <FileStatusBadge status={file.status} />
                <span>{formatBytes(file.size)}</span>
                <span>· {formatRelativeTime(file.createdAtUtc)}</span>
              </div>
            </div>
            {actions(file)}
          </li>
        ))}
      </ul>
    </>
  )
}
