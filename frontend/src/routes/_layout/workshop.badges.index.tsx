// Badge catalog: list definitions, lesson link, authenticated images; edit, recipients, delete; links to wizard and leaderboard.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  isRedirect,
  Link,
  redirect,
} from "@tanstack/react-router"
import { useState } from "react"

import { UsersService, WorkshopBadgesService } from "@/client"
import { AuthenticatedBadgeImage } from "@/components/Common/AuthenticatedBadgeImage"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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

function WorkshopBadgesHub() {
  const queryClient = useQueryClient()
  const [recipientBadgeId, setRecipientBadgeId] = useState<string | null>(null)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)
  const [orgRevoke, setOrgRevoke] = useState<{
    userId: string
    badgeId: string
  } | null>(null)
  const [orgRevokeReason, setOrgRevokeReason] = useState("")

  const { data, isLoading, error } = useQuery({
    queryKey: ["workshop-badges"],
    queryFn: () => WorkshopBadgesService.readWorkshopBadges(),
  })

  const recipientsQuery = useQuery({
    queryKey: ["workshop-badge-grants", recipientBadgeId],
    queryFn: () =>
      WorkshopBadgesService.readWorkshopBadgeGrantRecipients({
        badgeId: recipientBadgeId!,
      }),
    enabled: recipientBadgeId !== null,
  })

  const deleteMutation = useMutation({
    mutationFn: (badgeId: string) =>
      WorkshopBadgesService.deleteWorkshopBadge({ badgeId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      setDeleteTargetId(null)
    },
  })

  const orgRevokeMutation = useMutation({
    mutationFn: ({
      userId,
      badgeId,
      reason,
    }: {
      userId: string
      badgeId: string
      reason: string
    }) =>
      WorkshopBadgesService.revokeWorkshopBadgeOrg({
        requestBody: {
          user_id: userId,
          badge_id: badgeId,
          reason,
        },
      }),
    onSuccess: async () => {
      await recipientsQuery.refetch()
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      await queryClient.invalidateQueries({
        queryKey: ["workshop-badges-global-leaderboard"],
      })
      setOrgRevoke(null)
      setOrgRevokeReason("")
    },
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
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
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
                    {b.image_url ? (
                      <AuthenticatedBadgeImage
                        badgeId={b.id}
                        width={40}
                        height={40}
                        className="rounded-md border object-cover"
                        data-testid={`workshop-badge-img-${b.id}`}
                      />
                    ) : (
                      <img
                        src="/badge-default.svg"
                        alt=""
                        width={40}
                        height={40}
                        className="rounded-md border object-cover"
                        data-testid={`workshop-badge-img-${b.id}`}
                      />
                    )}
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
                      "-"
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button variant="outline" size="sm" asChild>
                        <Link
                          to="/workshop/badges/$badgeId/edit"
                          params={{ badgeId: b.id }}
                          data-testid={`workshop-badge-edit-${b.id}`}
                        >
                          Edit
                        </Link>
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`workshop-badge-recipients-${b.id}`}
                        onClick={() => setRecipientBadgeId(b.id)}
                      >
                        Recipients
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        data-testid={`workshop-badge-delete-${b.id}`}
                        onClick={() => setDeleteTargetId(b.id)}
                      >
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            {!isLoading && data?.count === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
                  No badges yet. Create one or sync a lesson repo with a v2
                  manifest.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>

      <Dialog
        open={recipientBadgeId !== null}
        onOpenChange={(open) => {
          if (!open) setRecipientBadgeId(null)
        }}
      >
        <DialogContent showCloseButton className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Badge recipients</DialogTitle>
            <DialogDescription>
              Active grants for this badge. Organization-wide grants can be
              revoked here; session grants are managed from the workshop
              session.
            </DialogDescription>
          </DialogHeader>
          {recipientsQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : recipientsQuery.data?.data?.length === 0 ? (
            <p className="text-muted-foreground text-sm">No active grants.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Learner</TableHead>
                  <TableHead>Granted</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recipientsQuery.data?.data?.map((row) => (
                  <TableRow key={`${row.user_id}-${row.session_id ?? "org"}`}>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium">
                          {row.full_name ?? row.email}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {row.email}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {row.granted_at
                        ? new Date(row.granted_at).toLocaleString()
                        : "-"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.session_id ? "Workshop session" : "Organization"}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.session_id ? (
                        <span className="text-muted-foreground text-xs">-</span>
                      ) : (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-testid={`workshop-badge-org-revoke-open-${row.user_id}`}
                          onClick={() =>
                            setOrgRevoke({
                              userId: row.user_id,
                              badgeId: recipientBadgeId!,
                            })
                          }
                        >
                          Revoke org grant
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={orgRevoke !== null}
        onOpenChange={(open) => {
          if (!open) {
            setOrgRevoke(null)
            setOrgRevokeReason("")
          }
        }}
      >
        <DialogContent showCloseButton>
          <DialogHeader>
            <DialogTitle>Revoke organization grant?</DialogTitle>
            <DialogDescription>
              A short reason is required. This does not affect session-scoped
              grants.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="workshop-badge-org-revoke-reason">Reason</Label>
            <Input
              id="workshop-badge-org-revoke-reason"
              data-testid="workshop-badge-org-revoke-reason"
              value={orgRevokeReason}
              onChange={(e) => setOrgRevokeReason(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setOrgRevoke(null)
                setOrgRevokeReason("")
              }}
              disabled={orgRevokeMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              data-testid="workshop-badge-org-revoke-confirm"
              disabled={
                orgRevokeMutation.isPending ||
                orgRevokeReason.trim().length === 0 ||
                orgRevoke === null
              }
              onClick={() => {
                if (orgRevoke === null) return
                orgRevokeMutation.mutate({
                  userId: orgRevoke.userId,
                  badgeId: orgRevoke.badgeId,
                  reason: orgRevokeReason.trim(),
                })
              }}
            >
              {orgRevokeMutation.isPending ? "Revoking…" : "Confirm revoke"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTargetId !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTargetId(null)
        }}
      >
        <DialogContent showCloseButton>
          <DialogHeader>
            <DialogTitle>Delete badge definition?</DialogTitle>
            <DialogDescription>
              This cannot be undone. Deletes are blocked while any active grant
              exists for this badge.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteTargetId(null)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              data-testid="workshop-badge-delete-confirm"
              disabled={deleteMutation.isPending || deleteTargetId === null}
              onClick={() => {
                if (deleteTargetId === null) return
                deleteMutation.mutate(deleteTargetId)
              }}
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
