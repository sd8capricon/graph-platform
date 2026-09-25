import { Skeleton } from '@/components/ui/skeleton'

interface TableSkeletonProps {
  rows?: number
  columns?: number
}

/** A shaped placeholder, so the page does not jump when real rows arrive. */
export function TableSkeleton({ rows = 6, columns = 4 }: TableSkeletonProps) {
  return (
    <div className="space-y-3" aria-hidden="true">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex items-center gap-4">
          {Array.from({ length: columns }, (_, column) => (
            <Skeleton
              key={column}
              className="h-5"
              style={{ width: column === 0 ? '28%' : `${Math.max(12, 60 / columns)}%` }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
