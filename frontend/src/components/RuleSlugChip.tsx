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
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-info/10 text-info-ink${className ? ` ${className}` : ""}`}
    >
      {children}
    </span>
  )
}
