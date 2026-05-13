import { SiGithub } from "react-icons/si"
import { Button } from "@/components/ui/button"

export function GitHubLoginButton() {
  const authjsUrl = import.meta.env.VITE_AUTHJS_URL
  if (!authjsUrl) return null

  const onClick = () => {
    const callbackUrl = `${window.location.origin}/auth/callback`
    const base = authjsUrl.replace(/\/$/, "")
    const target = `${base}/auth/signin?${new URLSearchParams({
      callbackUrl,
      provider: "github",
    }).toString()}`
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
