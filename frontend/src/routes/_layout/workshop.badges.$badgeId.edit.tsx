// Edit an existing workshop badge (title, points, description; slug only when not lesson-linked).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  isRedirect,
  Link,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"

import { UsersService, WorkshopBadgesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { isLoggedIn } from "@/hooks/useAuth"
import {
  type DashboardLandingPath,
  getDashboardLandingPath,
} from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/workshop/badges/$badgeId/edit")({
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_instructor && !user.is_superuser) {
        const target: DashboardLandingPath = getDashboardLandingPath(user)
        throw redirect({ to: target })
      }
    } catch (err) {
      if (isRedirect(err)) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: WorkshopBadgeEditPage,
  head: () => ({
    meta: [{ title: "Edit badge - Workshop" }],
  }),
})

function WorkshopBadgeEditPage() {
  const { badgeId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const {
    data: badge,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["workshop-badge", badgeId],
    queryFn: () => WorkshopBadgesService.readWorkshopBadge({ badgeId }),
  })

  const [slug, setSlug] = useState("")
  const [title, setTitle] = useState("")
  const [points, setPoints] = useState("5")
  const [description, setDescription] = useState("")
  const [file, setFile] = useState<File | null>(null)

  useEffect(() => {
    if (!badge) return
    setSlug(badge.slug)
    setTitle(badge.title)
    setPoints(String(badge.points))
    setDescription(badge.description ?? "")
  }, [badge])

  const updateMutation = useMutation({
    mutationFn: async () => {
      const pts = Number.parseInt(points, 10)
      if (!title.trim() || Number.isNaN(pts)) {
        throw new Error("invalid")
      }
      const body: {
        title: string
        points: number
        description?: string | null
        slug?: string
      } = {
        title: title.trim(),
        points: pts,
        description: description.trim() || null,
      }
      if (!badge?.lesson_id) {
        body.slug = slug.trim()
      }
      await WorkshopBadgesService.updateWorkshopBadge({
        badgeId,
        requestBody: body,
      })
      if (file) {
        await WorkshopBadgesService.uploadWorkshopBadgeImage({
          badgeId,
          formData: { file },
        })
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      await queryClient.invalidateQueries({
        queryKey: ["workshop-badge", badgeId],
      })
      await navigate({ to: "/workshop/badges" })
    },
  })

  return (
    <div
      className="mx-auto max-w-lg space-y-6"
      data-testid="workshop-badge-edit"
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Edit badge</h1>
        <p className="text-muted-foreground text-sm">
          {badge?.lesson_id
            ? "Lesson-linked badge: slug cannot be changed here."
            : "Stand-alone badge: you may change the slug if it stays unique."}
        </p>
      </div>

      {error ? (
        <p className="text-destructive text-sm" role="alert">
          Could not load badge.
        </p>
      ) : null}

      {isLoading || !badge ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <div className="space-y-4 rounded-md border p-4">
          <div className="space-y-2">
            <Label htmlFor="badge-slug-edit">Slug</Label>
            <Input
              id="badge-slug-edit"
              data-testid="workshop-badge-edit-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              disabled={Boolean(badge.lesson_id)}
              autoComplete="off"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="badge-title-edit">Title</Label>
            <Input
              id="badge-title-edit"
              data-testid="workshop-badge-edit-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="badge-points-edit">Points</Label>
            <Input
              id="badge-points-edit"
              data-testid="workshop-badge-edit-points"
              type="number"
              min={0}
              value={points}
              onChange={(e) => setPoints(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="badge-desc-edit">Description</Label>
            <Input
              id="badge-desc-edit"
              data-testid="workshop-badge-edit-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="badge-file-edit">Replace image (optional)</Label>
            <Input
              id="badge-file-edit"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              data-testid="workshop-badge-edit-file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              data-testid="workshop-badge-edit-submit"
              disabled={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
            >
              {updateMutation.isPending ? "Saving…" : "Save changes"}
            </Button>
            <Button type="button" variant="outline" asChild>
              <Link to="/workshop/badges">Cancel</Link>
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
