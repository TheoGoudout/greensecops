import type { FixStatus } from "@/client"

export function analysisStatusColor(status: string): string {
  switch (status) {
    case "completed":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "running":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "pending":
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
    case "no_workflows":
      return "bg-muted text-muted-foreground"
    default:
      return "bg-muted text-muted-foreground"
  }
}

export function analysisStatusLabel(status: string): string {
  switch (status) {
    case "no_workflows":
      return "No workflows"
    default:
      return status.replace(/_/g, " ")
  }
}

export function fixStatusColor(status: FixStatus): string {
  switch (status) {
    case "delivered":
      return "bg-green-500/15 text-green-700 dark:text-green-400"
    case "ready":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-400"
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-400"
    case "rejected":
      return "bg-muted text-muted-foreground line-through"
    default:
      return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400"
  }
}
