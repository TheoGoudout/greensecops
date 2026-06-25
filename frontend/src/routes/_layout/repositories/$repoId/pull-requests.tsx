import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { GitPullRequest } from "lucide-react"
import { useMemo, useState } from "react"
import { FixesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { PAGE_SIZE } from "@/lib/workflow-utils"

export const Route = createFileRoute(
  "/_layout/repositories/$repoId/pull-requests",
)({
  component: PullRequestsPage,
  head: () => ({
    meta: [{ title: "Pull Requests - GreenSecOps" }],
  }),
})

function PullRequestsPage() {
  const { repoId } = Route.useParams()
  const [stateFilter, setStateFilter] = useState<string>("all")
  const [page, setPage] = useState(0)

  const { data: fixes, isLoading } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const allGsPrs = useMemo(() => {
    if (!fixes) return []
    const seen = new Set<string>()
    return fixes
      .filter((f) => f.pr_url)
      .filter((f) => {
        if (seen.has(f.pr_url!)) return false
        seen.add(f.pr_url!)
        return true
      })
      .sort(
        (a, b) =>
          new Date(b.created_at ?? 0).getTime() -
          new Date(a.created_at ?? 0).getTime(),
      )
  }, [fixes])

  const filtered = useMemo(() => {
    if (stateFilter === "all") return allGsPrs
    return allGsPrs.filter((f) => (f.pr_state ?? "open") === stateFilter)
  }, [allGsPrs, stateFilter])

  const paged = useMemo(
    () => filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filtered, page],
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <Select
          value={stateFilter}
          onValueChange={(v) => {
            setStateFilter(v)
            setPage(0)
          }}
        >
          <SelectTrigger className="w-36 h-8 text-xs">
            <SelectValue placeholder="Filter by state" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
            <SelectItem value="merged">Merged</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {filtered.length} PR{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              {stateFilter === "all"
                ? "No GreenSecOps-created PRs yet. Generate and deliver fixes to see them here."
                : `No ${stateFilter} PRs.`}
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[1fr_6rem_8rem] items-center px-4 sm:px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                <span>Pull Request</span>
                <span className="text-center">State</span>
                <span className="text-right">Date</span>
              </div>
              <div className="divide-y">
                {paged.map((fix) => {
                  const state = fix.pr_state ?? "open"
                  const stateCls =
                    state === "merged"
                      ? "bg-purple-500/15 text-purple-700 dark:text-purple-400"
                      : state === "closed"
                        ? "bg-red-500/15 text-red-700 dark:text-red-400"
                        : "bg-green-500/15 text-green-700 dark:text-green-400"
                  return (
                    <div
                      key={fix.pr_url}
                      className="grid grid-cols-[1fr_6rem_8rem] items-center px-4 sm:px-6 py-3 gap-4"
                    >
                      <a
                        href={fix.pr_url!}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-mono text-blue-600 dark:text-blue-400 hover:underline truncate flex items-center gap-1.5"
                      >
                        <GitPullRequest className="h-3 w-3 shrink-0" />
                        {fix.pr_url!.replace("https://github.com/", "")}
                      </a>
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize text-center ${stateCls}`}
                      >
                        {state}
                      </span>
                      <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap text-right">
                        {fix.delivered_at
                          ? new Date(fix.delivered_at).toLocaleDateString(
                              undefined,
                              {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )
                          : "—"}
                      </span>
                    </div>
                  )
                })}
              </div>
              {filtered.length > PAGE_SIZE && (
                <div className="flex items-center justify-between px-6 py-3 border-t">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {page + 1} of{" "}
                    {Math.ceil(filtered.length / PAGE_SIZE)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(page + 1) * PAGE_SIZE >= filtered.length}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
