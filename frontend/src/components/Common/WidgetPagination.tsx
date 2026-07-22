import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface WidgetPaginationProps {
  pageIndex: number
  pageSize: number
  totalItems: number
  onPrevious: () => void
  onNext: () => void
  className?: string
}

export function WidgetPagination({
  pageIndex,
  pageSize,
  totalItems,
  onPrevious,
  onNext,
  className,
}: WidgetPaginationProps) {
  const pageCount = Math.ceil(totalItems / pageSize)
  if (pageCount <= 1) return null

  const from = pageIndex * pageSize + 1
  const to = Math.min((pageIndex + 1) * pageSize, totalItems)

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 px-6 py-3 border-t",
        className,
      )}
    >
      <span className="text-xs text-muted-foreground">
        Showing {from}-{to} of {totalItems}
      </span>
      <div className="flex items-center gap-x-3">
        <span className="text-xs text-muted-foreground">
          Page {pageIndex + 1} of {pageCount}
        </span>
        <div className="flex items-center gap-x-1">
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onPrevious}
            disabled={pageIndex === 0}
          >
            <span className="sr-only">Go to previous page</span>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onNext}
            disabled={pageIndex >= pageCount - 1}
          >
            <span className="sr-only">Go to next page</span>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
