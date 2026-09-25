import * as React from 'react'
import { Upload } from 'lucide-react'

import { env } from '@/app/env'
import { Button } from '@/components/ui/button'
import { formatBytes } from '@/lib/format'
import { cn } from '@/lib/utils'

interface FileDropzoneProps {
  onFiles: (files: File[]) => void
  disabled?: boolean
}

/**
 * Drag-and-drop plus a real file input.
 *
 * The size check happens here so a 500 MB mistake fails instantly instead of
 * after a long upload that Kestrel aborts mid-flight.
 */
export function FileDropzone({ onFiles, disabled = false }: FileDropzoneProps) {
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = React.useState(false)

  const accept = (list: FileList | null) => {
    if (!list || list.length === 0) return
    onFiles([...list])
    // Allow re-picking the same file straight after a failure.
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div
      onDragOver={(event) => {
        if (disabled) return
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        if (disabled) return
        event.preventDefault()
        setDragging(false)
        accept(event.dataTransfer.files)
      }}
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-8 text-center transition-colors',
        dragging && 'border-primary bg-primary/5',
        disabled && 'opacity-60',
      )}
    >
      <Upload className="size-6 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm font-medium">Drag files here, or choose them</p>
      <p className="text-xs text-muted-foreground">
        One file per upload · up to {formatBytes(env.maxUploadBytes)} each
      </p>

      <input
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        disabled={disabled}
        onChange={(event) => accept(event.target.files)}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        Choose files
      </Button>
    </div>
  )
}
