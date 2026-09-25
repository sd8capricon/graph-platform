import * as React from 'react'
import { Eye, EyeOff } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

type SecretInputProps = Omit<React.ComponentProps<typeof Input>, 'type'>

/** A write-only credential field: the API never returns a stored key to prefill. */
export function SecretInput({ className, ...props }: SecretInputProps) {
  const [visible, setVisible] = React.useState(false)

  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? 'text' : 'password'}
        autoComplete="off"
        spellCheck={false}
        className={cn('pr-10', className)}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="absolute top-1/2 right-1 size-7 -translate-y-1/2"
        onClick={() => setVisible((value) => !value)}
      >
        {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        <span className="sr-only">{visible ? 'Hide' : 'Show'} the value</span>
      </Button>
    </div>
  )
}
