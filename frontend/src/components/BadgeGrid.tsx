import { Check, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

/**
 * Base for every badge URL.
 *
 * The public URL wins when set: badge images are embedded in READMEs and
 * rendered by GitHub's camo proxy, which has to reach the API from outside
 * the deployment.
 */
export const BADGE_API_BASE =
  import.meta.env.VITE_GREENSECOPS_PUBLIC_URL || import.meta.env.VITE_API_URL

/**
 * Append the server-minted HMAC signature a private subject's badge needs.
 *
 * Public subjects use the plain URL — the signature is what authorises the
 * badge endpoint to answer for something the requester cannot otherwise read.
 */
export function signedBadgeUrl(base: string, sig: string | null | undefined) {
  return sig ? `${base}?sig=${sig}` : base
}

export interface BadgeEntry {
  key: string
  /** Repository name, or "repo / path" when the subject is a sub-path. */
  title: string
  svgUrl: string
  markdown: string
}

function BadgeCard({ entry }: { entry: BadgeEntry }) {
  const [copiedText, copy] = useCopyToClipboard()
  const copied = copiedText === entry.markdown

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{entry.title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <img
            src={entry.svgUrl}
            alt={`GreenSecOps badge for ${entry.title}`}
            className="h-5"
            onError={(e) => {
              // A badge for a subject that has never been graded 404s. Hiding
              // the broken image keeps the markdown — the thing being copied —
              // usable in the meantime.
              ;(e.target as HTMLImageElement).style.display = "none"
            }}
          />
        </div>
        <code className="text-xs text-muted-foreground bg-muted rounded px-2 py-1.5 break-all block">
          {entry.markdown}
        </code>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5 w-fit"
          onClick={() => copy(entry.markdown)}
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

interface BadgeGridProps {
  entries: BadgeEntry[]
  isLoading: boolean
  isError: boolean
  errorLabel: string
  emptyLabel: string
}

/**
 * The badge list and its four states, shared by every engine's badge tab.
 *
 * Each engine differs only in how it builds a URL and labels a subject, so
 * they hand over finished {@link BadgeEntry} values and share everything else.
 */
export function BadgeGrid({
  entries,
  isLoading,
  isError,
  errorLabel,
  emptyLabel,
}: BadgeGridProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-40 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return <p className="text-sm text-destructive">{errorLabel}</p>
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center">{emptyLabel}</p>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {entries.map((entry) => (
        <BadgeCard key={entry.key} entry={entry} />
      ))}
    </div>
  )
}
