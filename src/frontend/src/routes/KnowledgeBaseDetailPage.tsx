import * as React from 'react'
import { ArrowLeft, Database, Pencil, Rocket, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { env } from '@/app/env'
import { KnowledgeBaseState, type FileDto } from '@/api/types'
import { ActionTooltip } from '@/components/data/ActionTooltip'
import { announce } from '@/components/feedback/announcer'
import { ConfirmDialog } from '@/components/feedback/ConfirmDialog'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { PageHeader } from '@/components/feedback/PageHeader'
import { TableSkeleton } from '@/components/feedback/TableSkeleton'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { FileDropzone } from '@/features/knowledge-bases/FileDropzone'
import { FilesTable } from '@/features/knowledge-bases/FilesTable'
import {
  FileUploadQueue,
  type UploadTask,
} from '@/features/knowledge-bases/FileUploadQueue'
import { KbStateBadge } from '@/features/knowledge-bases/KbStateBadge'
import { RenameKnowledgeBaseDialog } from '@/features/knowledge-bases/RenameKnowledgeBaseDialog'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { formatBytes, formatDateTime } from '@/lib/format'
import { newUuid } from '@/lib/uuid'
import { useCurrentOrg } from '@/org/use-current-org'
import {
  useDeleteKnowledgeBase,
  useKnowledgeBaseQuery,
  usePublishKnowledgeBase,
} from '@/queries/use-knowledge-bases'
import {
  useDeleteFile,
  useDownloadFile,
  useFilesQuery,
  useUploadFile,
} from '@/queries/use-files'

const NEEDS_ROLE = 'You need the Contributor or Organization Admin role.'
const DRAFT_ONLY = 'Only a draft knowledge base can be changed.'

export function KnowledgeBaseDetailPage() {
  const { knowledgeBaseId = '' } = useParams<{ knowledgeBaseId: string }>()
  const { organizationId, canAuthor } = useCurrentOrg()
  const navigate = useNavigate()

  const knowledgeBaseQuery = useKnowledgeBaseQuery(organizationId, knowledgeBaseId)
  const knowledgeBase = knowledgeBaseQuery.data

  useDocumentTitle(knowledgeBase?.name ?? 'Knowledge base')

  // The detail response already embeds the files, so seed rather than refetch.
  const filesQuery = useFilesQuery(organizationId, knowledgeBaseId, knowledgeBase?.files)

  const uploadFile = useUploadFile(organizationId, knowledgeBaseId)
  const deleteFile = useDeleteFile(organizationId, knowledgeBaseId)
  const downloadFile = useDownloadFile(organizationId, knowledgeBaseId)
  const publish = usePublishKnowledgeBase(organizationId)
  const removeKnowledgeBase = useDeleteKnowledgeBase(organizationId)

  const [tasks, setTasks] = React.useState<UploadTask[]>([])
  const controllers = React.useRef(new Map<string, AbortController>())
  const [renameOpen, setRenameOpen] = React.useState(false)
  const [publishOpen, setPublishOpen] = React.useState(false)
  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [pendingFileDelete, setPendingFileDelete] = React.useState<FileDto | null>(null)
  const [downloadingId, setDownloadingId] = React.useState<string | null>(null)

  const isDraft = knowledgeBase?.state === KnowledgeBaseState.Draft
  const mutateReason = !canAuthor ? NEEDS_ROLE : !isDraft ? DRAFT_ONLY : null

  const startUpload = (files: File[]) => {
    for (const file of files) {
      const id = newUuid()

      if (file.size === 0) {
        setTasks((current) => [
          ...current,
          {
            id,
            fileName: file.name,
            size: 0,
            progress: 0,
            status: 'error',
            error: 'The file is empty.',
          },
        ])
        continue
      }

      // Checked client-side so an oversized file fails at once, rather than
      // after a long upload the server aborts.
      if (file.size > env.maxUploadBytes) {
        setTasks((current) => [
          ...current,
          {
            id,
            fileName: file.name,
            size: file.size,
            progress: 0,
            status: 'error',
            error: `Files may be at most ${formatBytes(env.maxUploadBytes)}.`,
          },
        ])
        continue
      }

      const controller = new AbortController()
      controllers.current.set(id, controller)

      setTasks((current) => [
        ...current,
        { id, fileName: file.name, size: file.size, progress: 0, status: 'uploading' },
      ])

      uploadFile.mutate(
        {
          file,
          signal: controller.signal,
          onProgress: (fraction) =>
            setTasks((current) =>
              current.map((task) =>
                task.id === id ? { ...task, progress: fraction } : task,
              ),
            ),
        },
        {
          onSuccess: (created) => {
            controllers.current.delete(id)
            setTasks((current) => current.filter((task) => task.id !== id))
            announce(`${created.fileName} uploaded`)
          },
          onError: (uploadError) => {
            controllers.current.delete(id)
            if (uploadError instanceof DOMException && uploadError.name === 'AbortError') {
              setTasks((current) => current.filter((task) => task.id !== id))
              return
            }
            const message = isApiError(uploadError)
              ? (uploadError.detail ?? uploadError.title)
              : 'Upload failed.'
            setTasks((current) =>
              current.map((task) =>
                task.id === id ? { ...task, status: 'error', error: message } : task,
              ),
            )
          },
        },
      )
    }
  }

  if (knowledgeBaseQuery.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-28 w-full" />
        <TableSkeleton rows={4} columns={5} />
      </div>
    )
  }

  if (knowledgeBaseQuery.isError) {
    const notFound = isApiError(knowledgeBaseQuery.error) && knowledgeBaseQuery.error.status === 404
    if (notFound) {
      return (
        <EmptyState
          icon={Database}
          title="Knowledge base not found"
          description="It may have been deleted, or it belongs to another organization."
          action={
            <Button asChild variant="outline">
              <Link to={`/orgs/${organizationId}/knowledge-bases`}>
                <ArrowLeft aria-hidden="true" />
                Back to knowledge bases
              </Link>
            </Button>
          }
        />
      )
    }
    return (
      <ErrorState
        error={knowledgeBaseQuery.error}
        onRetry={() => void knowledgeBaseQuery.refetch()}
      />
    )
  }

  // `knowledgeBase` was captured before the guards above, so it still needs
  // narrowing; the query guarantees it is set once loading and error are ruled out.
  if (!knowledgeBase) return null

  const files = filesQuery.data ?? []

  return (
    <>
      <PageHeader
        title={knowledgeBase.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <KbStateBadge state={knowledgeBase.state} />
            <span>Updated {formatDateTime(knowledgeBase.updatedAtUtc)}</span>
          </span>
        }
        actions={
          <>
            <ActionTooltip reason={mutateReason}>
              <Button
                variant="outline"
                disabled={!!mutateReason}
                aria-disabled={!!mutateReason}
                onClick={() => setRenameOpen(true)}
              >
                <Pencil aria-hidden="true" />
                Rename
              </Button>
            </ActionTooltip>

            <ActionTooltip
              reason={
                !canAuthor
                  ? NEEDS_ROLE
                  : !isDraft
                    ? 'This knowledge base has already been published.'
                    : null
              }
            >
              <Button
                disabled={!canAuthor || !isDraft}
                aria-disabled={!canAuthor || !isDraft}
                onClick={() => setPublishOpen(true)}
              >
                <Rocket aria-hidden="true" />
                Publish
              </Button>
            </ActionTooltip>

            <ActionTooltip reason={mutateReason}>
              <Button
                variant="outline"
                className="text-destructive hover:text-destructive"
                disabled={!!mutateReason}
                aria-disabled={!!mutateReason}
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 aria-hidden="true" />
                Delete
              </Button>
            </ActionTooltip>
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
          <CardDescription>
            Content comes from the files uploaded below.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">Created</dt>
              <dd className="text-sm">{formatDateTime(knowledgeBase.createdAtUtc)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Files</dt>
              <dd className="text-sm">{files.length}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Files</CardTitle>
          <CardDescription>
            {isDraft
              ? 'Upload the source documents to be indexed.'
              : 'A published knowledge base is read-only.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {canAuthor && isDraft ? (
            <FileDropzone onFiles={startUpload} />
          ) : (
            <p className="rounded-md border border-dashed px-4 py-3 text-sm text-muted-foreground">
              {!canAuthor
                ? 'You do not have permission to upload files here.'
                : 'Files cannot be changed once indexing has started.'}
            </p>
          )}

          <FileUploadQueue
            tasks={tasks}
            onCancel={(id) => {
              controllers.current.get(id)?.abort()
              controllers.current.delete(id)
              setTasks((current) => current.filter((task) => task.id !== id))
            }}
            onDismiss={(id) => setTasks((current) => current.filter((t) => t.id !== id))}
          />

          {filesQuery.isPending ? (
            <TableSkeleton rows={3} columns={5} />
          ) : filesQuery.isError ? (
            <ErrorState error={filesQuery.error} onRetry={() => void filesQuery.refetch()} />
          ) : files.length === 0 ? (
            <EmptyState
              title="No files yet"
              description={
                isDraft
                  ? 'Upload at least one file before publishing.'
                  : 'No files were uploaded to this knowledge base.'
              }
            />
          ) : (
            <FilesTable
              files={files}
              deleteReason={mutateReason}
              downloadingId={downloadingId}
              deletingId={deleteFile.isPending ? (pendingFileDelete?.id ?? null) : null}
              onDownload={(file) => {
                setDownloadingId(file.id)
                downloadFile.mutate(file, {
                  onError: (downloadError) =>
                    toast.error(
                      isApiError(downloadError)
                        ? (downloadError.detail ?? downloadError.title)
                        : 'Could not download the file.',
                    ),
                  onSettled: () => setDownloadingId(null),
                })
              }}
              onDelete={setPendingFileDelete}
            />
          )}
        </CardContent>
      </Card>

      {renameOpen ? (
        <RenameKnowledgeBaseDialog
          knowledgeBase={knowledgeBase}
          organizationId={organizationId}
          onClose={() => setRenameOpen(false)}
        />
      ) : null}

      <ConfirmDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        title={`Publish ${knowledgeBase.name}?`}
        description="Publishing starts indexing and locks the knowledge base: its name and files can no longer be changed."
        confirmLabel="Publish"
        pending={publish.isPending}
        onConfirm={() =>
          publish.mutate(knowledgeBase.id, {
            onSuccess: () => {
              toast.success('Indexing started')
              announce('Indexing started')
              setPublishOpen(false)
            },
            onError: (publishError) => {
              toast.error(
                isApiError(publishError)
                  ? (publishError.detail ?? publishError.title)
                  : 'Could not publish.',
              )
              setPublishOpen(false)
            },
          })
        }
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Delete ${knowledgeBase.name}?`}
        description="Its files and their stored content are deleted too. This cannot be undone."
        confirmLabel="Delete"
        destructive
        pending={removeKnowledgeBase.isPending}
        onConfirm={() =>
          removeKnowledgeBase.mutate(knowledgeBase.id, {
            onSuccess: () => {
              toast.success(`Deleted ${knowledgeBase.name}`)
              void navigate(`/orgs/${organizationId}/knowledge-bases`, { replace: true })
            },
            onError: (deleteError) => {
              toast.error(
                isApiError(deleteError)
                  ? (deleteError.detail ?? deleteError.title)
                  : 'Could not delete.',
              )
              setDeleteOpen(false)
            },
          })
        }
      />

      <ConfirmDialog
        open={pendingFileDelete !== null}
        onOpenChange={(open) => !open && setPendingFileDelete(null)}
        title={`Delete ${pendingFileDelete?.fileName ?? 'this file'}?`}
        description="The stored content is removed as well. This cannot be undone."
        confirmLabel="Delete"
        destructive
        pending={deleteFile.isPending}
        onConfirm={() => {
          if (!pendingFileDelete) return
          const name = pendingFileDelete.fileName
          deleteFile.mutate(pendingFileDelete.id, {
            onSuccess: () => {
              toast.success(`Deleted ${name}`)
              setPendingFileDelete(null)
            },
            onError: (fileError) => {
              toast.error(
                isApiError(fileError)
                  ? (fileError.detail ?? fileError.title)
                  : 'Could not delete the file.',
              )
              setPendingFileDelete(null)
            },
          })
        }}
      />
    </>
  )
}
