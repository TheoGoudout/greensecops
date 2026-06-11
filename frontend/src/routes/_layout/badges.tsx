import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Check, Copy } from "lucide-react"
import type { RepositoryPublic } from "@/client"
import { RepositoriesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

export const Route = createFileRoute("/_layout/badges")({
  component: Badges,
  head: () => ({
    meta: [{ title: "Badges - GreenSecOps" }],
  }),
})

const API_BASE = "https://api.greensecops.io"

function badgeSvgUrl(repo: RepositoryPublic): string {
  const [owner, name] = repo.full_name.split("/")
  return `${API_BASE}/${owner}/${name}/${repo.default_branch}.svg`
}

function badgeMarkdown(repo: RepositoryPublic): string {
  const url = badgeSvgUrl(repo)
  return `![GreenSecOps](${url})`
}

function BadgeRow({ repo }: { repo: RepositoryPublic }) {
  const [copiedText, copy] = useCopyToClipboard()
  const markdown = badgeMarkdown(repo)
  const svgUrl = badgeSvgUrl(repo)
  const copied = copiedText === markdown

  return (
    <div className="flex items-center justify-between gap-4 px-6 py-4">
      <div className="flex items-center gap-4 min-w-0">
        <img
          src={svgUrl}
          alt={`GreenSecOps badge for ${repo.full_name}`}
          className="h-5 shrink-0"
          onError={(e) => {
            ;(e.target as HTMLImageElement).style.display = "none"
          }}
        />
        <div className="min-w-0">
          <p className="text-sm font-medium truncate">{repo.full_name}</p>
          <code className="text-xs text-muted-foreground break-all">
            {markdown}
          </code>
        </div>
      </div>

      <Button
        variant="outline"
        size="sm"
        className="gap-1.5 shrink-0"
        onClick={() => copy(markdown)}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-green-600" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  )
}

function Badges() {
  const {
    data: repos,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["repositories"],
    queryFn: () => RepositoriesService.listRepositories({ limit: 200 }),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Badges</h1>
        <p className="text-muted-foreground">
          Embed GreenSecOps grade badges in your repository READMEs
        </p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground font-normal">
            Copy the Markdown snippet and paste it into your{" "}
            <code className="text-foreground font-mono text-xs">README.md</code>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive p-6">
              Failed to load repositories.
            </p>
          ) : !repos?.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No repositories found.
            </p>
          ) : (
            <div className="divide-y">
              {repos.map((repo) => (
                <BadgeRow key={repo.id} repo={repo} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
