// Badge catalog: list definitions, lesson link, image or default artwork; links to wizard and global leaderboard.
import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  isRedirect,
  Link,
  redirect,
} from "@tanstack/react-router"

import { OpenAPI, UsersService, WorkshopBadgesService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { getDashboardLandingPath } from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/workshop/badges/")({
  beforeLoad: async () => {
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_instructor && !user.is_superuser) {
        const target = getDashboardLandingPath(user)
        throw redirect({ to: target })
      }
    } catch (err) {
      if (isRedirect(err)) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: WorkshopBadgesHub,
  head: () => ({
    meta: [{ title: "Badges - Workshop" }],
  }),
})

function badgeImageSrc(imageUrl: string | null | undefined): string {
  if (!imageUrl) return "/badge-default.svg"
  if (imageUrl.startsWith("http")) return imageUrl
  const base = OpenAPI.BASE?.replace(/\/$/, "") ?? ""
  return `${base}${imageUrl}`
}

function WorkshopBadgesHub() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["workshop-badges"],
    queryFn: () => WorkshopBadgesService.readWorkshopBadges(),
  })

  return (
    <div className="space-y-6" data-testid="workshop-badges-hub">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Badge management
          </h1>
          <p className="text-muted-foreground text-sm">
            Catalog synced from lesson manifests (v2) or created here. Upload
            images per badge; otherwise a default icon is shown.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link
              to="/workshop/badges/leaderboard"
              data-testid="workshop-badges-link-leaderboard"
            >
              Global leaderboard
            </Link>
          </Button>
          <Button asChild>
            <Link
              to="/workshop/badges/new"
              data-testid="workshop-badges-link-new"
            >
              New badge
            </Link>
          </Button>
        </div>
      </div>

      {error ? (
        <p className="text-destructive text-sm" role="alert">
          Could not load badges.
        </p>
      ) : null}

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">Image</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Slug</TableHead>
              <TableHead>Points</TableHead>
              <TableHead>Lesson</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            ) : null}
            {!isLoading &&
              data?.data?.map((b) => (
                <TableRow
                  key={b.id}
                  data-testid={`workshop-badge-row-${b.slug}`}
                >
                  <TableCell>
                    <img
                      src={badgeImageSrc(b.image_url)}
                      alt=""
                      width={40}
                      height={40}
                      className="rounded-md border object-cover"
                      data-testid={`workshop-badge-img-${b.id}`}
                    />
                  </TableCell>
                  <TableCell className="font-medium">{b.title}</TableCell>
                  <TableCell className="font-mono text-xs">{b.slug}</TableCell>
                  <TableCell>{b.points}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {b.lesson_title ? (
                      <span>
                        {b.lesson_title}{" "}
                        <span className="font-mono">({b.lesson_slug})</span>
                      </span>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            {!isLoading && data?.count === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  No badges yet. Create one or sync a lesson repo with a v2
                  manifest.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
