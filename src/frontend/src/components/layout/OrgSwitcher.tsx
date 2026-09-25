import * as React from 'react'
import { Check, ChevronsUpDown, Plus } from 'lucide-react'
import { useNavigate } from 'react-router'

import { useAuth } from '@/auth/use-auth'
import { ROLE_LABELS } from '@/org/permissions'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

interface OrgSwitcherProps {
  currentOrganizationId?: string
}

/**
 * Switching organization is a navigation, not a state change: the organization
 * lives in the URL, so a query key can never disagree with what is on screen.
 */
export function OrgSwitcher({ currentOrganizationId }: OrgSwitcherProps) {
  const { memberships } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = React.useState(false)

  const current = memberships.find(
    (entry) => entry.organizationId === currentOrganizationId,
  )

  // ⌘K / Ctrl+K opens the switcher from anywhere.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Switch organization"
          className="w-full justify-between font-normal"
        >
          <span className="truncate">
            {current?.organizationName ?? 'Select organization'}
          </span>
          <span className="flex items-center gap-1">
            <kbd className="hidden rounded border bg-muted px-1 text-[10px] text-muted-foreground sm:inline">
              ⌘K
            </kbd>
            <ChevronsUpDown className="size-4 shrink-0 opacity-50" aria-hidden="true" />
          </span>
        </Button>
      </PopoverTrigger>

      <PopoverContent className="w-(--radix-popover-trigger-width) min-w-56 p-0" align="start">
        <Command>
          <CommandInput placeholder="Find an organization…" />
          <CommandList>
            <CommandEmpty>No organization found.</CommandEmpty>
            <CommandGroup heading="Organizations">
              {memberships.map((membership) => (
                <CommandItem
                  key={membership.organizationId}
                  value={membership.organizationName}
                  onSelect={() => {
                    setOpen(false)
                    // Return to the section root: a resource id from one
                    // organization does not exist in another.
                    void navigate(`/orgs/${membership.organizationId}`)
                  }}
                >
                  <Check
                    className={cn(
                      'size-4',
                      membership.organizationId === currentOrganizationId
                        ? 'opacity-100'
                        : 'opacity-0',
                    )}
                    aria-hidden="true"
                  />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate">{membership.organizationName}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {ROLE_LABELS[membership.role]}
                    </span>
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup>
              <CommandItem
                value="__all-organizations"
                onSelect={() => {
                  setOpen(false)
                  void navigate('/orgs')
                }}
              >
                <Plus className="size-4" aria-hidden="true" />
                All organizations
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
