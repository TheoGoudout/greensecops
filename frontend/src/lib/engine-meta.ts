import type { LucideIcon } from "lucide-react"
import { Activity, Boxes, Cloud, Container, Workflow } from "lucide-react"
import type { Engine, OverviewSection, Severity } from "@/client"

/**
 * How each analysis engine presents itself on the dashboard.
 *
 * The icons match what the sidebar already uses for the same area, so a Docker
 * row on the dashboard and the Docker nav entry read as the same thing.
 */
export const ENGINE_META: Record<
  Engine,
  { icon: LucideIcon; label: string; blurb: string; to: string }
> = {
  workflow: {
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
  // No dashboard block of its own yet — the overview reports the four engines
  // that grade a target. Listed so this record stays total over `Engine`, and
  // so the telemetry tab has a label to share when it grows one.
  telemetry: {
    icon: Activity,
    label: "Telemetry",
    blurb: "Measured runtime data from completed workflow runs",
    to: "/repositories",
  },
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
export const SEVERITY_FILL: Record<Severity, string> = {
  critical: "bg-red-600 dark:bg-red-500",
  high: "bg-orange-500 dark:bg-orange-400",
  medium: "bg-yellow-500 dark:bg-yellow-400",
  low: "bg-blue-500 dark:bg-blue-400",
  info: "bg-slate-400 dark:bg-slate-500",
}
