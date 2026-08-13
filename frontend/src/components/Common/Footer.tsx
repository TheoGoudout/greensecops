import { useQuery } from "@tanstack/react-query"

import { UtilsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  APP_ENVIRONMENT,
  APP_VERSION,
  displayVersion,
  IS_PRODUCTION,
} from "@/lib/version"

export function Footer() {
  const currentYear = new Date().getFullYear()

  // The dashboard and the API are promoted through different platforms —
  // Cloudflare Workers and Coolify — so this bundle cannot infer what the API
  // is running. release-deploy.yml deploys them in order and waits, but a
  // half-finished promotion is still possible, and this is what makes it
  // visible rather than leaving it to surface as a confusing error later.
  //
  // Deliberately quiet on failure: an unreachable API already shows itself
  // everywhere else in the UI, and a footer is the wrong place to raise it.
  const { data: api } = useQuery({
    queryKey: ["api-version"],
    queryFn: () => UtilsService.version(),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const mismatch = api != null && api.version !== APP_VERSION

  return (
    <footer className="border-t py-4 px-6">
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 sm:justify-between">
        <p className="text-muted-foreground text-sm">
          GreenSecOps - {currentYear}
        </p>

        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-muted-foreground text-xs font-mono">
                {displayVersion()}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <p>Dashboard {displayVersion()}</p>
              <p>API {api ? `v${api.version}` : "unavailable"}</p>
            </TooltipContent>
          </Tooltip>

          {!IS_PRODUCTION && (
            <Badge variant="secondary" className="text-xs">
              {APP_ENVIRONMENT}
            </Badge>
          )}

          {mismatch && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="destructive" className="text-xs">
                  API v{api.version}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <p>
                  The API is on v{api.version} but this dashboard was built for
                  v{APP_VERSION}.
                </p>
                <p>A deployment is probably still in progress.</p>
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
    </footer>
  )
}
