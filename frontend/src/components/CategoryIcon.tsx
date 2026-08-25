import type { Category } from "@/client"
import { cn } from "@/lib/utils"

interface CategoryIconProps {
  category: Category
  className?: string
  withLabel?: boolean
}

export const CATEGORY_META: Record<Category, { icon: string; label: string }> =
  {
    energy: { icon: "⚡", label: "Energy" },
    reliability: { icon: "🛡️", label: "Reliability" },
    security: { icon: "🔒", label: "Security" },
    performance: { icon: "🚀", label: "Performance" },
    maintainability: { icon: "🔧", label: "Maintainability" },
  }

export function CategoryIcon({
  category,
  className,
  withLabel = false,
}: CategoryIconProps) {
  const meta = CATEGORY_META[category]

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <span aria-hidden="true">{meta.icon}</span>
      {withLabel && <span className="capitalize text-sm">{meta.label}</span>}
    </span>
  )
}
