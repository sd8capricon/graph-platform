import * as React from 'react'
import { Search, X } from 'lucide-react'

import { announce } from '@/components/feedback/announcer'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface DataToolbarProps {
  search: string
  onSearchChange: (value: string) => void
  searchPlaceholder?: string
  searchLabel?: string
  matchedCount: number
  totalCount: number
  noun: string
  isFiltered: boolean
  onClearFilters?: () => void
  /** Extra filter controls, rendered beside the search box. */
  children?: React.ReactNode
}

export function DataToolbar({
  search,
  onSearchChange,
  searchPlaceholder = 'Search…',
  searchLabel = 'Search',
  matchedCount,
  totalCount,
  noun,
  isFiltered,
  onClearFilters,
  children,
}: DataToolbarProps) {
  const inputId = React.useId()

  // Speak the result count once it settles, since a filtered table has no
  // other announcement that anything changed.
  React.useEffect(() => {
    if (!isFiltered) return
    announce(`Showing ${matchedCount} of ${totalCount} ${noun}`)
  }, [isFiltered, matchedCount, totalCount, noun])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative w-full sm:max-w-xs">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <label htmlFor={inputId} className="sr-only">
            {searchLabel}
          </label>
          <Input
            id={inputId}
            type="search"
            value={search}
            placeholder={searchPlaceholder}
            className="pl-8"
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>

        {children ? (
          <div className="flex flex-wrap items-center gap-2">{children}</div>
        ) : null}

        {isFiltered && onClearFilters ? (
          <Button variant="ghost" size="sm" onClick={onClearFilters} className="sm:ml-auto">
            <X aria-hidden="true" />
            Clear filters
          </Button>
        ) : null}
      </div>

      <p className="text-xs text-muted-foreground">
        {isFiltered
          ? `Showing ${matchedCount} of ${totalCount} ${noun}`
          : `${totalCount} ${noun}`}
      </p>
    </div>
  )
}
