import { useCallback, useState } from "react"
import type { OverviewSection } from "@/client"

const STORAGE_KEY = "greensecops.dashboard.collapsedSections"

function read(): Set<OverviewSection> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed)
      ? new Set(parsed as OverviewSection[])
      : new Set()
  } catch {
    // Private-mode / quota-exceeded / corrupt value — a remembered fold state
    // is never worth failing the page render over.
    return new Set()
  }
}

/**
 * Which dashboard sections are folded away, persisted across reloads.
 *
 * Stores the *collapsed* set rather than the expanded one so a section added
 * later defaults to open — the alternative silently hides new engines from
 * anyone who has visited the dashboard before.
 */
export function useCollapsedSections() {
  const [collapsed, setCollapsed] = useState<Set<OverviewSection>>(read)

  const toggle = useCallback((section: OverviewSection) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(section)) {
        next.delete(section)
      } else {
        next.add(section)
      }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]))
      } catch {
        // Fold state is a convenience; losing it must not break the toggle.
      }
      return next
    })
  }, [])

  return { collapsed, toggle }
}
