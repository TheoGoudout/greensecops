import { Github } from "lucide-react"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"

const GITHUB_APP_NAME = import.meta.env.VITE_GITHUB_APP_NAME as string

const GitHubIntegration = () => {
  const { user: currentUser } = useAuth()

  const installUrl = `https://github.com/apps/${GITHUB_APP_NAME}/installations/new`

  return (
    <div className="max-w-md">
      <h3 className="text-lg font-semibold py-4">GitHub Integration</h3>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">GitHub account</p>
          {currentUser?.github_username ? (
            <p className="text-sm text-muted-foreground py-1">
              Connected as{" "}
              <span className="font-mono font-medium text-foreground">
                @{currentUser.github_username}
              </span>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground py-1">
              No GitHub account linked. Sign in with GitHub to connect.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">GitHub App installation</p>
          <p className="text-sm text-muted-foreground">
            Install the GreenSecOps GitHub App on your repositories to enable
            automated analysis.
          </p>
          <div className="pt-2">
            <Button variant="outline" className="gap-2" asChild>
              <a href={installUrl} target="_blank" rel="noopener noreferrer">
                <Github className="h-4 w-4" />
                {currentUser?.github_username
                  ? "Manage GitHub App installation"
                  : "Install GitHub App"}
              </a>
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default GitHubIntegration
