import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const PAGE_SIZES = [25, 50, 100]

interface ClientPaginationProps {
  pageIndex: number
  pageCount: number
  pageSize: number
  matchedCount: number
  onPageChange: (index: number) => void
  onPageSizeChange: (size: number) => void
}

/** Pagination over an already-fetched array; the API has no paging parameters. */
export function ClientPagination({
  pageIndex,
  pageCount,
  pageSize,
  matchedCount,
  onPageChange,
  onPageSizeChange,
}: ClientPaginationProps) {
  if (matchedCount <= PAGE_SIZES[0] && pageCount <= 1) return null

  return (
    <nav
      aria-label="Pagination"
      className="flex flex-col items-center justify-between gap-3 sm:flex-row"
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Rows per page</span>
        <Select
          value={String(pageSize)}
          onValueChange={(value) => onPageSizeChange(Number(value))}
        >
          <SelectTrigger size="sm" className="w-20" aria-label="Rows per page">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZES.map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2">
        <span aria-live="polite" className="text-xs text-muted-foreground">
          Page {pageIndex + 1} of {pageCount}
        </span>
        <Button
          variant="outline"
          size="icon"
          className="size-8"
          disabled={pageIndex === 0}
          onClick={() => onPageChange(pageIndex - 1)}
        >
          <ChevronLeft aria-hidden="true" />
          <span className="sr-only">Previous page</span>
        </Button>
        <Button
          variant="outline"
          size="icon"
          className="size-8"
          disabled={pageIndex >= pageCount - 1}
          onClick={() => onPageChange(pageIndex + 1)}
        >
          <ChevronRight aria-hidden="true" />
          <span className="sr-only">Next page</span>
        </Button>
      </div>
    </nav>
  )
}
