import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import type { ComponentProps } from "react"

import type { WorkshopSessionListItem } from "@/client"
import { WorkshopSessionsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

function statusBadgeVariant(
  status: string,
): ComponentProps<typeof Badge>["variant"] {
  if (status === "live") return "default"
  if (status === "paused") return "secondary"
  if (status === "scheduled") return "outline"
  if (status === "ended") return "outline"
  return "outline"
}

function RoleBadge({ role }: { role: WorkshopSessionListItem["my_role"] }) {
  if (role === "instructor")
    return <Badge variant="secondary">Instructor</Badge>
  if (role === "participant")
    return <Badge variant="outline">Participant</Badge>
  return (
    <Badge variant="outline" className="text-muted-foreground">
      Admin view
    </Badge>
  )
}

export function DashboardWorkshopSessions({
  className,
  heading = "Your workshops",
  description = "Sessions where you have a roster seat — open to jump into /workshop (no peer list here).",
  workshopsHubLink,
}: {
  className?: string
  heading?: string
  description?: string
  /** Instructor / admin: link from card header to the workshops hub route */
  workshopsHubLink?: boolean
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["workshopSessionsForUser"],
    queryFn: () =>
      WorkshopSessionsService.readWorkshopSessionsForUser({
        skip: 0,
        limit: 50,
      }),
  })

  return (
    <Card data-testid="dashboard-workshop-sessions" className={cn(className)}>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="text-base">{heading}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        {workshopsHubLink ? (
          <Link
            to="/workshops"
            className="text-primary text-sm font-medium underline underline-offset-4"
          >
            Workshops hub
          </Link>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-muted-foreground text-sm">Loading sessions…</p>
        ) : null}
        {isError ? (
          <p className="text-destructive text-sm">
            {(error as Error)?.message ?? "Could not load sessions"}
          </p>
        ) : null}
        {data && data.count === 0 ? (
          <p className="text-muted-foreground text-sm">
            No workshops yet — you’ll see sessions once you’re on a roster.
          </p>
        ) : null}
        {data && data.data.length > 0 ? (
          <ul className="divide-border divide-y rounded-lg border">
            {data.data.map((row) => (
              <li key={row.id}>
                <Link
                  to="/workshop/$sessionId"
                  params={{ sessionId: row.id }}
                  className="hover:bg-accent/60 flex flex-col gap-2 px-3 py-3 text-sm transition-colors sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0 space-y-1">
                    <p className="truncate font-medium">{row.lesson_title}</p>
                    <p className="text-muted-foreground truncate text-xs">
                      {row.lesson_slug}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <Badge variant={statusBadgeVariant(row.status)}>
                      {row.status}
                    </Badge>
                    <RoleBadge role={row.my_role ?? null} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  )
}
