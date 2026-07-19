import type { ReactNode } from "react"

/**
 * Rounded status pill. `colorClass` comes from lib/status-colors; `className`
 * carries site-specific extras (capitalize, shrink-0, ...).
 */
export function StatusPill({
  colorClass,
  className,
  children,
}: {
  colorClass: string
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded-full${className ? ` ${className}` : ""} ${colorClass}`}
    >
      {children}
    </span>
  )
}
