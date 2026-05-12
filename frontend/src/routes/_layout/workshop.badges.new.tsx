// Wizard: create a non-lesson badge (slug, title, points, description) and optional image upload.
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  isRedirect,
  Link,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { useState } from "react"

import { UsersService, WorkshopBadgesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { isLoggedIn } from "@/hooks/useAuth"
import {
  type DashboardLandingPath,
  getDashboardLandingPath,
} from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/workshop/badges/new")({
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
  component: WorkshopBadgeNewWizard,
  head: () => ({
    meta: [{ title: "New badge - Workshop" }],
  }),
})

function WorkshopBadgeNewWizard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [slug, setSlug] = useState("")
  const [title, setTitle] = useState("")
  const [points, setPoints] = useState("5")
  const [description, setDescription] = useState("")
  const [file, setFile] = useState<File | null>(null)

  const createMutation = useMutation({
    mutationFn: async () => {
      const pts = Number.parseInt(points, 10)
      if (!slug.trim() || !title.trim() || Number.isNaN(pts)) {
        throw new Error("invalid")
      }
      const created = await WorkshopBadgesService.createWorkshopBadge({
        requestBody: {
          slug: slug.trim(),
          title: title.trim(),
          description: description.trim() || null,
          points: pts,
        },
      })
      if (file) {
        await WorkshopBadgesService.uploadWorkshopBadgeImage({
          badgeId: created.id,
          formData: { file },
        })
      }
      return created
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      await navigate({ to: "/workshop/badges" })
    },
  })

  return (
    <div
      className="mx-auto max-w-lg space-y-6"
      data-testid="workshop-badge-wizard"
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New badge</h1>
        <p className="text-muted-foreground text-sm">
          Stand-alone badge (not tied to a lesson). Slug must be unique and
          kebab-case.
        </p>
      </div>

      <div className="space-y-4 rounded-md border p-4">
        <div className="space-y-2">
          <Label htmlFor="badge-slug">Slug</Label>
          <Input
            id="badge-slug"
            data-testid="workshop-badge-wizard-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="e.g. mentor-of-the-week"
            autoComplete="off"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="badge-title">Title</Label>
          <Input
            id="badge-title"
            data-testid="workshop-badge-wizard-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Display name"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="badge-points">Points</Label>
          <Input
            id="badge-points"
            data-testid="workshop-badge-wizard-points"
            type="number"
            min={0}
            max={1000}
            value={points}
            onChange={(e) => setPoints(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="badge-desc">Description (optional)</Label>
          <Input
            id="badge-desc"
            data-testid="workshop-badge-wizard-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="badge-file">
            Image (optional, PNG/JPEG/WebP, max 512KB)
          </Label>
          <Input
            id="badge-file"
            data-testid="workshop-badge-wizard-file"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        {createMutation.isError ? (
          <p className="text-destructive text-sm" role="alert">
            {createMutation.error instanceof Error &&
            createMutation.error.message === "invalid"
              ? "Fill slug, title, and valid points."
              : "Request failed."}
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button
            type="button"
            data-testid="workshop-badge-wizard-submit"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? "Saving…" : "Create badge"}
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link to="/workshop/badges">Cancel</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
