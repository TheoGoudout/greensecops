import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Check, Copy } from "lucide-react"
import type { TerraformRootPublic } from "@/client"
import { TerraformService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

export const Route = createFileRoute("/_layout/infrastructure/badges")({
  component: TerraformBadges,
  head: () => ({
    meta: [{ title: "Terraform Badges - GreenSecOps" }],
  }),
})

const API_BASE =
  import.meta.env.VITE_GREENSECOPS_PUBLIC_URL || import.meta.env.VITE_API_URL

function terraformBadgeSvgUrl(root: TerraformRootPublic): string {
  const base = `${API_BASE}/api/v1/badges/terraform/${root.id}.svg`
  return root.badge_sig ? `${base}?sig=${root.badge_sig}` : base
}

function terraformBadgeMarkdown(root: TerraformRootPublic): string {
  const url = terraformBadgeSvgUrl(root)
  return `![GreenSecOps Terraform](${url})`
}

function TerraformBadgeCard({ root }: { root: TerraformRootPublic }) {
  const [copiedText, copy] = useCopyToClipboard()
  const markdown = terraformBadgeMarkdown(root)
  const svgUrl = terraformBadgeSvgUrl(root)
  const copied = copiedText === markdown
  const label = root.repo_full_name
    ? `${root.repo_full_name} / ${root.root_path}`
    : root.root_path

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{label}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <img
            src={svgUrl}
            alt={`Terraform badge for ${label}`}
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

function TerraformBadges() {
  const {
    data: terraformRoots,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["terraform-roots"],
    queryFn: () => TerraformService.listTerraformRoots({}),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Terraform Badges</h1>
        <p className="text-muted-foreground">
          Embed Terraform grade badges in your repository READMEs
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
          Failed to load Terraform roots.
        </p>
      ) : !terraformRoots?.length ? (
        <p className="text-sm text-muted-foreground text-center">
          No Terraform roots configured.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {terraformRoots.map((root) => (
            <TerraformBadgeCard key={root.id} root={root} />
          ))}
        </div>
      )}
    </div>
  )
}
