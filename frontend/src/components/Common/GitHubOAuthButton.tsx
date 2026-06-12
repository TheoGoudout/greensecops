import { FaGithub } from "react-icons/fa"
import { Button } from "@/components/ui/button"

export function GitHubOAuthButton() {
  const handleClick = () => {
    window.location.href = `${import.meta.env.VITE_API_URL}/api/v1/auth/github/login`
  }

  return (
    <Button
      type="button"
      variant="outline"
      className="w-full"
      onClick={handleClick}
    >
      <FaGithub className="mr-2 h-4 w-4" />
      Continue with GitHub
    </Button>
  )
}
