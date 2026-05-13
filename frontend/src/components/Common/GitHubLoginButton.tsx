import { SiGithub } from "react-icons/si"
import { Button } from "@/components/ui/button"

export function GitHubLoginButton() {
  const authjsUrl = import.meta.env.VITE_AUTHJS_URL
  if (!authjsUrl) return null

  const onClick = () => {
    const callbackUrl = `${window.location.origin}/auth/callback`
    const target = `${authjsUrl.replace(
      /\/$/,
      "",
    )}/api/auth/signin?provider=github&callbackUrl=${encodeURIComponent(callbackUrl)}`
    window.location.href = target
  }

  return (
    <Button
      type="button"
      variant="outline"
      onClick={onClick}
      data-testid="github-login-button"
      className="w-full"
    >
      <SiGithub className="size-4" />
      Continue with GitHub
    </Button>
  )
}
