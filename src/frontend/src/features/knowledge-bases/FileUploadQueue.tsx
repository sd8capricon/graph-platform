import { AlertCircle, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { formatBytes } from '@/lib/format'

export interface UploadTask {
  id: string
  fileName: string
  size: number
  progress: number
  status: 'uploading' | 'error'
  error?: string
}

interface FileUploadQueueProps {
  tasks: UploadTask[]
  onCancel: (id: string) => void
  onDismiss: (id: string) => void
}

export function FileUploadQueue({ tasks, onCancel, onDismiss }: FileUploadQueueProps) {
  if (tasks.length === 0) return null

  return (
    <ul className="space-y-3">
      {tasks.map((task) => (
        <li
          key={task.id}
          className={
            task.status === 'error'
              ? 'space-y-2 rounded-md border border-destructive/40 bg-destructive/5 p-3'
              : 'space-y-2 rounded-md border p-3'
          }
        >
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {task.fileName}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatBytes(task.size)}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 shrink-0"
              onClick={() =>
                task.status === 'error' ? onDismiss(task.id) : onCancel(task.id)
              }
            >
              <X aria-hidden="true" />
              <span className="sr-only">
                {task.status === 'error' ? 'Dismiss' : 'Cancel'} {task.fileName}
              </span>
            </Button>
          </div>

          {task.status === 'uploading' ? (
            <Progress
              value={Math.round(task.progress * 100)}
              aria-label={`Uploading ${task.fileName}`}
            />
          ) : (
            <p className="flex items-center gap-1.5 text-xs text-destructive">
              <AlertCircle className="size-3.5 shrink-0" aria-hidden="true" />
              {task.error}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}
