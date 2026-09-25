import * as React from 'react'
import { Loader2 } from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: React.ReactNode
  confirmLabel?: string
  destructive?: boolean
  pending?: boolean
  /** When set, the confirm button stays disabled until this exact text is typed. */
  confirmationPhrase?: string
  confirmationHint?: string
  onConfirm: () => void
}

/**
 * `AlertDialog` rather than `Dialog`: it is `role="alertdialog"` and focuses
 * Cancel by default, which is the right default for a destructive action.
 */
export function ConfirmDialog({ open, onOpenChange, ...body }: ConfirmDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts the content on close, so the body's state resets by
          itself and no reset-on-close effect is needed. */}
      <AlertDialogContent>
        <ConfirmDialogBody {...body} onOpenChange={onOpenChange} />
      </AlertDialogContent>
    </AlertDialog>
  )
}

type ConfirmDialogBodyProps = Omit<ConfirmDialogProps, 'open'>

function ConfirmDialogBody({
  title,
  description,
  confirmLabel = 'Confirm',
  destructive = false,
  pending = false,
  confirmationPhrase,
  confirmationHint,
  onConfirm,
}: ConfirmDialogBodyProps) {
  const [typed, setTyped] = React.useState('')
  const inputId = React.useId()

  const blocked = confirmationPhrase ? typed.trim() !== confirmationPhrase : false

  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription>{description}</AlertDialogDescription>
      </AlertDialogHeader>

      {confirmationPhrase ? (
        <div className="space-y-2">
          <Label htmlFor={inputId}>
            {confirmationHint ?? `Type “${confirmationPhrase}” to confirm`}
          </Label>
          <Input
            id={inputId}
            value={typed}
            autoComplete="off"
            onChange={(event) => setTyped(event.target.value)}
          />
        </div>
      ) : null}

      <AlertDialogFooter>
        <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
        <AlertDialogAction
          disabled={pending || blocked}
          variant={destructive ? 'destructive' : 'default'}
          onClick={(event) => {
            // Keep the dialog open while the request is in flight.
            event.preventDefault()
            onConfirm()
          }}
        >
          {pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
          {confirmLabel}
        </AlertDialogAction>
      </AlertDialogFooter>
    </>
  )
}
