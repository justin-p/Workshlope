// Global badge leaderboard: total points and badge counts for all users (authenticated).
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { useState } from "react"

import {
  OpenAPI,
  WorkshopBadgesService,
  type WorkshopGlobalLeaderboardRowPublic,
} from "@/client"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { isLoggedIn } from "@/hooks/useAuth"

const LEADERBOARD_NAME_PLACEHOLDER = "Unnamed learner"

function globalLeaderboardDisplayName(
  fullName: string | null | undefined,
): string {
  const t = fullName?.trim()
  return t && t.length > 0 ? t : LEADERBOARD_NAME_PLACEHOLDER
}

function globalLeaderboardAvatarFallback(
  fullName: string | null | undefined,
  userId: string,
): string {
  const t = fullName?.trim()
  if (t && t.length > 0) {
    const parts = t.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) {
      return (parts[0]![0]! + parts[1]![0]!).toUpperCase()
    }
    return t.slice(0, 2).toUpperCase()
  }
  return userId.replace(/-/g, "").slice(0, 2).toUpperCase()
}

function globalLeaderboardBadgeImageSrc(badgeId: string): string {
  const base = OpenAPI.BASE?.replace(/\/$/, "") ?? ""
  return `${base}/api/v1/workshop/badges/${badgeId}/image`
}

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
                <GlobalLeaderboardRow key={row.user_id} row={row} />
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

function GlobalLeaderboardRow({
  row,
}: {
  row: WorkshopGlobalLeaderboardRowPublic
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const displayName = globalLeaderboardDisplayName(row.full_name)
  const avatarLetters = globalLeaderboardAvatarFallback(
    row.full_name,
    row.user_id,
  )

  const { data: badgesData, isPending: badgesPending } = useQuery({
    queryKey: ["workshop-badges-global-leaderboard-user-badges", row.user_id],
    queryFn: () =>
      WorkshopBadgesService.readWorkshopGlobalLeaderboardUserBadges({
        userId: row.user_id,
      }),
    enabled: menuOpen,
  })

  return (
    <TableRow data-testid={`workshop-global-lb-row-${row.user_id}`}>
      <TableCell className="font-medium">{row.rank}</TableCell>
      <TableCell>
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="hover:bg-muted/50 -m-2 flex w-full max-w-md items-center gap-2 rounded-md p-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Show badges for ${displayName}`}
              data-testid={`workshop-global-lb-badges-trigger-${row.user_id}`}
            >
              <Avatar className="h-8 w-8">
                <AvatarImage src={row.avatar_url ?? undefined} alt="" />
                <AvatarFallback>{avatarLetters}</AvatarFallback>
              </Avatar>
              <span className="font-medium">{displayName}</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="max-h-80 min-w-[14rem] overflow-y-auto"
          >
            <DropdownMenuLabel>{displayName}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {badgesPending ? (
              <div className="text-muted-foreground px-2 py-1.5 text-sm">
                Loading…
              </div>
            ) : null}
            {!badgesPending && (badgesData?.data?.length ?? 0) === 0 ? (
              <div className="text-muted-foreground px-2 py-1.5 text-sm">
                No active badges.
              </div>
            ) : null}
            {!badgesPending &&
              badgesData?.data?.map((b) => (
                <DropdownMenuItem
                  key={b.badge_id}
                  disabled
                  className="flex cursor-default items-center gap-2 opacity-100 focus:bg-transparent data-[disabled]:opacity-100"
                  data-testid={`workshop-global-lb-badge-item-${b.slug}`}
                >
                  <img
                    src={globalLeaderboardBadgeImageSrc(b.badge_id)}
                    alt=""
                    className="h-7 w-7 shrink-0 rounded object-cover"
                    onError={(e) => {
                      e.currentTarget.src = "/badge-default.svg"
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">
                      {b.title}
                    </span>
                    <span className="text-muted-foreground font-mono text-xs">
                      {b.points} pts
                    </span>
                  </span>
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
      <TableCell
        className="text-right font-mono"
        data-testid={`workshop-global-lb-points-${row.user_id}`}
      >
        {row.total_points}
      </TableCell>
      <TableCell className="text-right font-mono">{row.badge_count}</TableCell>
    </TableRow>
  )
}
