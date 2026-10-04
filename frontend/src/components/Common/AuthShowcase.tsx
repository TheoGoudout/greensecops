import { GitPullRequest } from "lucide-react"

import { GradeBadge } from "@/components/GradeBadge"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"

const SEVERITY_SPLIT = [
  { cls: "bg-destructive", share: 8 },
  { cls: "bg-serious", share: 22 },
  { cls: "bg-warning", share: 38 },
  { cls: "bg-info", share: 32 },
]

/**
 * The sign-in screen's left column: what GreenSecOps does, shown with the
 * app's own components — a repository's grade, and a finding on its way to
 * a pull request.
 */
export function AuthShowcase() {
  return (
    <div className="hidden w-full max-w-md flex-col gap-8 lg:flex">
      <div className="flex flex-col gap-3">
        <p className="font-mono text-xs tracking-wider text-primary uppercase">
          Pipeline grading
        </p>
        <h2 className="text-4xl leading-tight font-bold">
          Grade every pipeline.{" "}
          <span className="text-signal">Ship the fixes as pull requests.</span>
        </h2>
      </div>

      <div className="flex flex-col gap-3">
        <div className="rounded-xl border bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="font-mono text-sm">acme/payments-api</span>
            <GradeBadge grade="A+" className="px-3 py-1 text-sm" />
          </div>
          <div className="mt-4 flex items-end gap-2">
            <span className="font-display text-4xl font-bold">92</span>
            <span className="mb-1 text-sm text-success-ink">
              +14 this month
            </span>
          </div>
          <div className="mt-4 flex h-1.5 gap-0.5 overflow-hidden rounded-full">
            {SEVERITY_SPLIT.map(({ cls, share }) => (
              <span key={cls} className={cls} style={{ width: `${share}%` }} />
            ))}
          </div>
        </div>

        <div className="ml-8 rounded-xl border bg-card p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityChip severity="high" />
            <RuleSlugChip>unpinned_actions</RuleSlugChip>
          </div>
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            .github/workflows/ci.yml:14
          </p>
          <p className="mt-3 flex items-center gap-1.5 text-sm font-medium text-success-ink">
            <GitPullRequest className="size-4" />
            Fix opened as PR #128
          </p>
        </div>
      </div>
    </div>
  )
}
