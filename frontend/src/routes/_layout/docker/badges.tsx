import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Check, Copy } from "lucide-react"
import type { DockerTargetPublic } from "@/client"
import { DockerService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

export const Route = createFileRoute("/_layout/docker/badges")({
  component: DockerBadges,
  head: () => ({
    meta: [{ title: "Docker Badges - GreenSecOps" }],
  }),
})

const API_BASE =
  import.meta.env.VITE_GREENSECOPS_PUBLIC_URL || import.meta.env.VITE_API_URL

function dockerBadgeSvgUrl(target: DockerTargetPublic): string {
  const base = `${API_BASE}/api/v1/badges/docker/${target.id}.svg`
  return target.badge_sig ? `${base}?sig=${target.badge_sig}` : base
}

function dockerBadgeMarkdown(target: DockerTargetPublic): string {
  return `![GreenSecOps Docker](${dockerBadgeSvgUrl(target)})`
}

function DockerBadgeCard({ target }: { target: DockerTargetPublic }) {
  const [copiedText, copy] = useCopyToClipboard()
  const markdown = dockerBadgeMarkdown(target)
  const svgUrl = dockerBadgeSvgUrl(target)
  const copied = copiedText === markdown
  // A root-path target covers the whole repo, so the repo name says it all —
  // appending "/" would just read as "acme/web-app / /".
  const repo = target.repo_full_name ?? target.repo_id
  const label = target.root_path ? `${repo} / ${target.root_path}` : repo

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{label}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <img
            src={svgUrl}
            alt={`Docker badge for ${label}`}
            className="h-5"
            onError={(e) => {
              ;(e.target as HTMLImageElement).style.display = "none"
            }}
          />
        </div>
        <code className="text-xs text-muted-foreground bg-muted rounded px-2 py-1.5 break-all block">
          {markdown}
        </code>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5 w-fit"
          onClick={() => copy(markdown)}
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-primary" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? "Copied" : "Copy Markdown"}
        </Button>
      </CardContent>
    </Card>
  )
}

function DockerBadges() {
  const {
    data: targets,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["docker-targets"],
    queryFn: () => DockerService.listDockerTargets({}),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Docker Badges</h1>
        <p className="text-muted-foreground">
          Embed Docker grade badges in your repository READMEs
        </p>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-destructive">
          Failed to load Docker targets.
        </p>
      ) : !targets?.length ? (
        <p className="text-sm text-muted-foreground text-center">
          No Docker targets configured.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {targets.map((target) => (
            <DockerBadgeCard key={target.id} target={target} />
          ))}
        </div>
      )}
    </div>
  )
}
