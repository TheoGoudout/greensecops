import type { ReactNode } from "react"

/** Blue monospace chip for a rule slug. */
export function RuleSlugChip({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300${className ? ` ${className}` : ""}`}
    >
      {children}
    </span>
  )
}
