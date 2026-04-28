import { useQuery } from "@tanstack/react-query"
import { Github } from "lucide-react"

import { OauthService } from "@/client"
import { Badge } from "@/components/ui/badge"

interface GitHubLinkBadgeProps {
  userId: string
}

export function GitHubLinkBadge({ userId }: GitHubLinkBadgeProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["users", userId, "github-link"],
    queryFn: () => OauthService.getLinkStatus({ userId }),
  })

  if (isLoading) {
    return <span className="text-muted-foreground text-xs">...</span>
  }

  if (!data) {
    return (
      <span className="text-muted-foreground text-xs">Not linked</span>
    )
  }

  return (
    <Badge
      variant="secondary"
      className="gap-1"
      data-testid={`github-linked-${userId}`}
    >
      <Github className="size-3" />
      {data.provider_login || data.provider_account_id}
    </Badge>
  )
}
