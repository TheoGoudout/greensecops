import type { LucideIcon } from "lucide-react"
import { Boxes, Cloud, Container, Workflow } from "lucide-react"
import type {
  IssueSeverity,
  OverviewEngineKey,
  OverviewSection,
} from "@/client"

/**
 * How each analysis engine presents itself on the dashboard.
 *
 * The icons match what the sidebar already uses for the same area, so a Docker
 * row on the dashboard and the Docker nav entry read as the same thing.
 */
export const ENGINE_META: Record<
  OverviewEngineKey,
  { icon: LucideIcon; label: string; blurb: string; to: string }
> = {
  ci: {
    icon: Workflow,
    label: "CI workflows",
    blurb: "GitHub Actions workflow files, per repository",
    to: "/repositories",
  },
  docker: {
    icon: Container,
    label: "Docker",
    blurb: "Dockerfiles and Compose files, per target folder",
    to: "/docker",
  },
  terraform: {
    icon: Boxes,
    label: "Terraform",
    blurb: "Terraform roots, per registered folder",
    to: "/infrastructure",
  },
  cloud: {
    icon: Cloud,
    label: "Cloud posture",
    blurb: "Live AWS account posture, per connected account",
    to: "/infrastructure",
  },
}

/**
 * The three collapsible sections, in pipeline order: build, package, then run.
 * Matches how the sidebar groups the same engines — Terraform and cloud
 * posture share the Infrastructure section, as they already share a page.
 */
export const SECTION_META: Record<
  OverviewSection,
  { title: string; engines: OverviewEngineKey[] }
> = {
  ci: { title: "CI workflows", engines: ["ci"] },
  docker: { title: "Docker", engines: ["docker"] },
  infra: { title: "Infrastructure", engines: ["terraform", "cloud"] },
}

export const SECTION_ORDER: OverviewSection[] = ["ci", "docker", "infra"]

/**
 * Fill for one severity in the stacked severity bar.
 *
 * These are the *status* palette, not categorical series colors — the same
 * red/orange/yellow/blue/gray ordering `SeverityChip` uses in every issue
 * list, so a red chip in a table and a red segment in a bar mean the same
 * thing. Status colors are exempt from the categorical CVD gates precisely
 * because they never carry identity alone: every bar that uses these ships a
 * visible count legend beside it, so the color is a second channel, never the
 * only one.
 */
export const SEVERITY_FILL: Record<IssueSeverity, string> = {
  critical: "bg-red-600 dark:bg-red-500",
  high: "bg-orange-500 dark:bg-orange-400",
  medium: "bg-yellow-500 dark:bg-yellow-400",
  low: "bg-blue-500 dark:bg-blue-400",
  info: "bg-slate-400 dark:bg-slate-500",
}

/** A short relative-time string ("3h ago"), or "never" for a missing date. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never"
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return "never"
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  return months < 12 ? `${months}mo ago` : `${Math.round(months / 12)}y ago`
}
