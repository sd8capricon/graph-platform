import * as React from 'react'

import { useDebouncedValue } from '@/hooks/use-debounced-value'

export type SortDirection = 'asc' | 'desc'

export interface ClientCollectionOptions<T> {
  items: T[] | undefined
  /** Fields concatenated and substring-matched against the search term. */
  searchFields: (item: T) => Array<string | null | undefined>
  /** Extra predicates, e.g. a state or role filter. Falsy entries are ignored. */
  filters?: Array<((item: T) => boolean) | null | undefined>
  sortKey?: keyof T & string
  sortDirection?: SortDirection
  sortAccessor?: (item: T, key: string) => string | number | null | undefined
  pageSize?: number
}

export interface ClientCollection<T> {
  /** The rows for the current page. */
  page: T[]
  /** Everything matching the search and filters, across all pages. */
  matched: T[]
  totalCount: number
  matchedCount: number
  pageIndex: number
  pageCount: number
  pageSize: number
  setPageIndex: (index: number) => void
  setPageSize: (size: number) => void
  search: string
  setSearch: (value: string) => void
  isFiltered: boolean
}

/**
 * Client-side search, filtering, sorting and pagination.
 *
 * No list endpoint on this API supports `?q=`, `?page=` or `?sort=` — each
 * returns its complete array with a fixed server-side order — so all of it has
 * to happen here. If a deployment ever grows lists into the thousands of rows,
 * that is the point at which this should become a server-side capability
 * rather than a bigger client-side filter.
 */
export function useClientCollection<T>({
  items,
  searchFields,
  filters,
  sortKey,
  sortDirection = 'asc',
  sortAccessor,
  pageSize: initialPageSize = 25,
}: ClientCollectionOptions<T>): ClientCollection<T> {
  const [search, setSearchRaw] = React.useState('')
  const [pageIndex, setPageIndex] = React.useState(0)
  const [pageSize, setPageSizeRaw] = React.useState(initialPageSize)

  const debouncedSearch = useDebouncedValue(search, 200)
  const term = debouncedSearch.trim().toLowerCase()

  const all = React.useMemo(() => items ?? [], [items])

  const activeFilters = React.useMemo(
    () => (filters ?? []).filter((filter): filter is (item: T) => boolean => !!filter),
    [filters],
  )

  const matched = React.useMemo(() => {
    let result = all

    if (term) {
      result = result.filter((item) =>
        searchFields(item).some((field) => field?.toLowerCase().includes(term)),
      )
    }

    for (const filter of activeFilters) {
      result = result.filter(filter)
    }

    if (sortKey) {
      const read = (item: T) =>
        sortAccessor ? sortAccessor(item, sortKey) : (item[sortKey] as unknown)
      result = [...result].sort((left, right) => {
        const a = read(left)
        const b = read(right)
        if (a == null && b == null) return 0
        if (a == null) return 1
        if (b == null) return -1
        const comparison =
          typeof a === 'number' && typeof b === 'number'
            ? a - b
            : String(a).localeCompare(String(b), undefined, { sensitivity: 'base' })
        return sortDirection === 'asc' ? comparison : -comparison
      })
    }

    return result
  }, [all, term, activeFilters, searchFields, sortKey, sortDirection, sortAccessor])

  const pageCount = Math.max(1, Math.ceil(matched.length / pageSize))
  const safePageIndex = Math.min(pageIndex, pageCount - 1)

  const page = React.useMemo(
    () => matched.slice(safePageIndex * pageSize, safePageIndex * pageSize + pageSize),
    [matched, safePageIndex, pageSize],
  )

  const setSearch = React.useCallback((value: string) => {
    setSearchRaw(value)
    setPageIndex(0)
  }, [])

  const setPageSize = React.useCallback((size: number) => {
    setPageSizeRaw(size)
    setPageIndex(0)
  }, [])

  return {
    page,
    matched,
    totalCount: all.length,
    matchedCount: matched.length,
    pageIndex: safePageIndex,
    pageCount,
    pageSize,
    setPageIndex,
    setPageSize,
    search,
    setSearch,
    isFiltered: term.length > 0 || activeFilters.length > 0,
  }
}
