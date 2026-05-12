// Global badge leaderboard: total points and badge counts for all users (authenticated).
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"

import { WorkshopBadgesService } from "@/client"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/workshop/badges/leaderboard")({
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
  },
  component: WorkshopBadgesLeaderboard,
  head: () => ({
    meta: [{ title: "Badge leaderboard - Workshop" }],
  }),
})

function WorkshopBadgesLeaderboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["workshop-badges-global-leaderboard"],
    queryFn: () => WorkshopBadgesService.readWorkshopGlobalBadgeLeaderboard(),
  })

  return (
    <div className="space-y-6" data-testid="workshop-badges-global-leaderboard">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Global badge leaderboard
        </h1>
        <p className="text-muted-foreground text-sm">
          Totals from session and organization-wide grants (revoked awards
          excluded).
        </p>
      </div>

      {error ? (
        <p className="text-destructive text-sm" role="alert">
          Could not load leaderboard.
        </p>
      ) : null}

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">Rank</TableHead>
              <TableHead>Learner</TableHead>
              <TableHead className="text-right">Points</TableHead>
              <TableHead className="text-right">Badges</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            ) : null}
            {!isLoading &&
              data?.data?.map((row) => (
                <TableRow
                  key={row.user_id}
                  data-testid={`workshop-global-lb-row-${row.user_id}`}
                >
                  <TableCell className="font-medium">{row.rank}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Avatar className="h-8 w-8">
                        <AvatarImage src={row.avatar_url ?? undefined} alt="" />
                        <AvatarFallback>
                          {(row.full_name ?? row.email)
                            .slice(0, 2)
                            .toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex flex-col">
                        <span className="font-medium">
                          {row.full_name ?? row.email}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {row.email}
                        </span>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell
                    className="text-right font-mono"
                    data-testid={`workshop-global-lb-points-${row.user_id}`}
                  >
                    {row.total_points}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {row.badge_count}
                  </TableCell>
                </TableRow>
              ))}
            {!isLoading && data?.count === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground">
                  No badge grants yet.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
