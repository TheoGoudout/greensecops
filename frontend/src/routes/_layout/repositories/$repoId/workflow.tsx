import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useMemo } from "react"
import type { FixPublic, IssuePublic } from "@/client"
import { FixesService, IssuesService, RepositoriesService } from "@/client"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { WorkflowFileViewer } from "@/components/WorkflowFileViewer"
import { Route as RepoRoute } from "@/routes/_layout/repositories/$repoId"

export const Route = createFileRoute("/_layout/repositories/$repoId/workflow")({
  component: WorkflowPage,
  head: () => ({
    meta: [{ title: "Workflow - GreenSecOps" }],
  }),
})

function WorkflowPage() {
  const { repoId } = Route.useParams()
  const { branch } = RepoRoute.useSearch()

  const { data: workflowFiles, isLoading: wfLoading } = useQuery({
    queryKey: ["workflow-files", repoId, { branch }],
    queryFn: () =>
      RepositoriesService.listWorkflowFiles({
        repoId,
        branch: branch || undefined,
      }),
  })

  const { data: issues } = useQuery({
    queryKey: ["issues", "repo", repoId, { unfixed: false, branch }],
    queryFn: () =>
      IssuesService.listIssues({
        repoId,
        limit: 200,
        branch: branch || undefined,
      }),
  })

  const { data: fixes } = useQuery({
    queryKey: ["fixes", "repo", repoId],
    queryFn: () => FixesService.listFixes({ repoId, limit: 100 }),
  })

  const issuesByPath = useMemo(() => {
    const map = new Map<string, IssuePublic[]>()
    for (const issue of issues ?? []) {
      const path = issue.workflow_file_path ?? ""
      const list = map.get(path) ?? []
      list.push(issue)
      map.set(path, list)
    }
    return map
  }, [issues])

  const fixByPath = useMemo(() => {
    const map = new Map<string, FixPublic>()
    for (const fix of fixes ?? []) {
      map.set(fix.workflow_file_path ?? "", fix)
    }
    return map
  }, [fixes])

  if (wfLoading) {
    return (
      <div className="flex flex-col gap-4">
        {[...Array(2)].map((_, i) => (
          <Skeleton key={i} className="h-48 w-full" />
        ))}
      </div>
    )
  }

  if (!workflowFiles?.length) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          No workflow files found. Run an analysis first.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {workflowFiles.map((wf) => {
        const fileIssues = issuesByPath.get(wf.path) ?? []
        const fileFix = fixByPath.get(wf.path)
        const showFix =
          fileFix?.status === "ready" || fileFix?.status === "delivered"
        return (
          <WorkflowFileViewer
            key={wf.id}
            path={wf.path}
            rawContent={wf.raw_content ?? ""}
            fullContent={
              showFix ? (fileFix?.full_content ?? undefined) : undefined
            }
            issues={fileIssues}
            fix={fileFix}
          />
        )
      })}
    </div>
  )
}
