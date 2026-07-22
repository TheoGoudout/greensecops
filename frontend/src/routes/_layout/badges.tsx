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

const API_BASE =
  import.meta.env.VITE_GREENSECOPS_PUBLIC_URL || import.meta.env.VITE_API_URL

function badgeSvgUrl(repo: RepositoryPublic): string {
  const [owner, name] = repo.full_name.split("/")
  const base = `${API_BASE}/api/v1/badges/${owner}/${name}/${repo.default_branch}.svg`
  // Private repos require the server-minted HMAC signature; public repos use
  // the plain URL.
  return repo.badge_sig ? `${base}?sig=${repo.badge_sig}` : base
}

function badgeMarkdown(repo: RepositoryPublic): string {
  const url = badgeSvgUrl(repo)
  return `![GreenSecOps](${url})`
}

function BadgeCard({ repo }: { repo: RepositoryPublic }) {
  const [copiedText, copy] = useCopyToClipboard()
  const markdown = badgeMarkdown(repo)
  const svgUrl = badgeSvgUrl(repo)
  const copied = copiedText === markdown

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">
          {repo.full_name}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <img
            src={svgUrl}
            alt={`GreenSecOps badge for ${repo.full_name}`}
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

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-destructive">Failed to load repositories.</p>
      ) : !repos?.length ? (
        <p className="text-sm text-muted-foreground text-center">
          No repositories found.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {repos.map((repo) => (
            <BadgeCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}
    </div>
  )
}
