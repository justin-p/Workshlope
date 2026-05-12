// Badge hub: catalog (optional archived), grant via org user search, recipients + revoke, leaderboard link.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  isRedirect,
  Link,
  redirect,
} from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"

import {
  ApiError,
  OpenAPI,
  UsersService,
  WorkshopBadgesService,
} from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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

const PICKER_LIMIT = 25
const PICKER_DEBOUNCE_MS = 350

function badgeImageSrc(imageUrl: string | null | undefined): string {
  if (!imageUrl) return "/badge-default.svg"
  if (imageUrl.startsWith("http")) return imageUrl
  const base = OpenAPI.BASE?.replace(/\/$/, "") ?? ""
  return `${base}${imageUrl}`
}

function WorkshopBadgesHub() {
  const queryClient = useQueryClient()
  const [includeArchived, setIncludeArchived] = useState(false)

  const [grantBadgeId, setGrantBadgeId] = useState<string | null>(null)
  const [grantBadgeSlug, setGrantBadgeSlug] = useState<string | null>(null)
  const [grantSearch, setGrantSearch] = useState("")
  const [grantQuery, setGrantQuery] = useState("")
  const [selectedGrantUserId, setSelectedGrantUserId] = useState<string | null>(
    null,
  )
  const [grantError, setGrantError] = useState<string | null>(null)

  const [recipientsBadgeId, setRecipientsBadgeId] = useState<string | null>(
    null,
  )
  const [recipientsBadgeSlug, setRecipientsBadgeSlug] = useState<string | null>(
    null,
  )
  const [revokeUserId, setRevokeUserId] = useState<string | null>(null)
  const [revokeReason, setRevokeReason] = useState("")
  const [recipientsError, setRecipientsError] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ["workshop-badges", includeArchived],
    queryFn: () =>
      WorkshopBadgesService.readWorkshopBadges({
        includeArchived,
      }),
  })

  useEffect(() => {
    const t = window.setTimeout(
      () => setGrantQuery(grantSearch.trim()),
      PICKER_DEBOUNCE_MS,
    )
    return () => window.clearTimeout(t)
  }, [grantSearch])

  useEffect(() => {
    if (grantBadgeId === null) {
      setGrantSearch("")
      setGrantQuery("")
      setSelectedGrantUserId(null)
      setGrantError(null)
    }
  }, [grantBadgeId])

  useEffect(() => {
    if (recipientsBadgeId === null) {
      setRevokeUserId(null)
      setRevokeReason("")
      setRecipientsError(null)
    }
  }, [recipientsBadgeId])

  const grantPickerQuery = useQuery({
    queryKey: [
      "workshop-badge-grant-picker",
      grantBadgeId,
      grantQuery,
      PICKER_LIMIT,
    ],
    queryFn: () =>
      WorkshopBadgesService.readWorkshopBadgeGrantUserPicker({
        badgeId: grantBadgeId!,
        q: grantQuery.length > 0 ? grantQuery : undefined,
        skip: 0,
        limit: PICKER_LIMIT,
      }),
    enabled: grantBadgeId !== null,
  })

  const _recipientsQuery = useQuery({
    queryKey: ["workshop-badge-recipients", recipientsBadgeId],
    queryFn: () =>
      WorkshopBadgesService.readWorkshopBadgeGrantRecipients({
        badgeId: recipientsBadgeId!,
      }),
    enabled: recipientsBadgeId !== null,
  })

  const grantMutation = useMutation({
    mutationFn: async ({
      badgeId,
      userId,
    }: {
      badgeId: string
      userId: string
    }) =>
      WorkshopBadgesService.grantWorkshopBadgeFromHub({
        badgeId,
        requestBody: { user_id: userId },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      await queryClient.invalidateQueries({
        queryKey: ["workshop-badge-recipients"],
      })
      setGrantBadgeId(null)
      setGrantBadgeSlug(null)
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setGrantError(body?.detail ?? e.message)
      } else {
        setGrantError(e instanceof Error ? e.message : "Grant failed")
      }
    },
  })

  const revokeMutation = useMutation({
    mutationFn: async ({
      badgeId,
      userId,
      reason,
    }: {
      badgeId: string
      userId: string
      reason: string
    }) =>
      WorkshopBadgesService.revokeWorkshopBadgeFromHub({
        badgeId,
        requestBody: { user_id: userId, reason },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["workshop-badge-recipients", recipientsBadgeId],
      })
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      setRevokeUserId(null)
      setRevokeReason("")
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setRecipientsError(body?.detail ?? e.message)
      } else {
        setRecipientsError(e instanceof Error ? e.message : "Revoke failed")
      }
    },
  })

  const recipientsQuery = useQuery({
    queryKey: ["workshop-badge-grants", recipientBadgeId],
    queryFn: () =>
      WorkshopBadgesService.readWorkshopBadgeGrantRecipients({
        badgeId: recipientBadgeId!,
      }),
    enabled: recipientBadgeId !== null,
  })

  const _deleteMutation = useMutation({
    mutationFn: (badgeId: string) =>
      WorkshopBadgesService.deleteWorkshopBadge({ badgeId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workshop-badges"] })
      setDeleteTargetId(null)
    },
  })

  const _orgRevokeMutation = useMutation({
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
            Catalog synced from lesson manifests (v2) or created here. Grant
            badges to people in your organization, or let the system award
            lesson-linked badges when a session ends.
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

      <div className="flex items-center gap-2">
        <Checkbox
          id="workshop-badges-include-archived"
          checked={includeArchived}
          onCheckedChange={(v) => setIncludeArchived(v === true)}
          data-testid="workshop-badges-hub-show-archived"
        />
        <Label
          htmlFor="workshop-badges-include-archived"
          className="text-sm font-normal"
        >
          Show archived badges
        </Label>
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
              data?.data?.map((b) => {
                const archived = Boolean(b.archived_at)
                return (
                  <TableRow
                    key={b.id}
                    data-testid={`workshop-badge-row-${b.slug}`}
                    className={archived ? "opacity-70" : undefined}
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
                    <TableCell className="font-medium">
                      <span className="mr-2">{b.title}</span>
                      {archived ? (
                        <span className="text-muted-foreground text-xs">
                          (archived)
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {b.slug}
                    </TableCell>
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
                    <TableCell className="text-right space-x-2 whitespace-nowrap">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`workshop-badge-hub-grant-open-${b.slug}`}
                        disabled={archived}
                        title={
                          archived
                            ? "Archived badges cannot receive new grants"
                            : undefined
                        }
                        onClick={() => {
                          setGrantBadgeId(b.id)
                          setGrantBadgeSlug(b.slug)
                        }}
                      >
                        Grant
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`workshop-badge-hub-recipients-open-${b.slug}`}
                        onClick={() => {
                          setRecipientsBadgeId(b.id)
                          setRecipientsBadgeSlug(b.slug)
                        }}
                      >
                        Recipients
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
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
        open={grantBadgeId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setGrantBadgeId(null)
            setGrantBadgeSlug(null)
          }
        }}
      >
        <DialogContent
          className="max-w-lg"
          data-testid="workshop-badge-grant-dialog"
        >
          <DialogHeader>
            <DialogTitle>Grant badge</DialogTitle>
            <DialogDescription>
              Search people in your organization, then grant this badge once.
              Someone who already has this badge will keep their existing grant.
            </DialogDescription>
          </DialogHeader>
          {grantBadgeSlug ? (
            <p className="text-muted-foreground text-xs font-mono">
              {grantBadgeSlug}
            </p>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="workshop-badge-grant-search">Find user</Label>
            <Input
              id="workshop-badge-grant-search"
              value={grantSearch}
              onChange={(e) => setGrantSearch(e.target.value)}
              placeholder="Email or name"
              autoComplete="off"
              data-testid="workshop-badge-grant-search"
            />
          </div>
          {grantError ? (
            <p className="text-destructive text-sm" role="alert">
              {grantError}
            </p>
          ) : null}
          <div
            className="max-h-60 overflow-auto rounded-md border"
            role="listbox"
            aria-label="Matching users"
          >
            {grantPickerQuery.isLoading ? (
              <div className="flex items-center gap-2 p-3 text-muted-foreground text-sm">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Searching…
              </div>
            ) : null}
            {!grantPickerQuery.isLoading &&
            (grantPickerQuery.data?.data.length ?? 0) === 0 ? (
              <p className="p-3 text-muted-foreground text-sm">No matches.</p>
            ) : null}
            {!grantPickerQuery.isLoading &&
              grantPickerQuery.data?.data.map((row) => {
                const selected = selectedGrantUserId === row.user_id
                return (
                  <button
                    key={row.user_id}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    data-testid={`workshop-badge-grant-user-row-${row.user_id}`}
                    className={`flex w-full flex-col items-start gap-0.5 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted/60 ${
                      selected ? "bg-muted" : ""
                    }`}
                    onClick={() => setSelectedGrantUserId(row.user_id)}
                  >
                    <span className="font-medium">
                      {row.full_name?.trim() || row.email}
                    </span>
                    <span className="text-muted-foreground text-xs">
                      {row.email}
                    </span>
                  </button>
                )
              })}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setGrantBadgeId(null)
                setGrantBadgeSlug(null)
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              data-testid="workshop-badge-grant-confirm"
              disabled={
                grantBadgeId === null ||
                selectedGrantUserId === null ||
                grantMutation.isPending
              }
              onClick={() => {
                if (grantBadgeId === null || selectedGrantUserId === null)
                  return
                setGrantError(null)
                grantMutation.mutate({
                  badgeId: grantBadgeId,
                  userId: selectedGrantUserId,
                })
              }}
            >
              {grantMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  Granting…
                </>
              ) : (
                "Grant badge"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={recipientsBadgeId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRecipientsBadgeId(null)
            setRecipientsBadgeSlug(null)
          }
        }}
      >
        <DialogContent
          className="max-w-lg"
          data-testid="workshop-badge-recipients-dialog"
        >
          <DialogHeader>
            <DialogTitle>Badge granted</DialogTitle>
            <DialogDescription>
              People who currently hold this badge. You can revoke a grant if
              you need to correct a mistake.
            </DialogDescription>
          </DialogHeader>
          {recipientsBadgeSlug ? (
            <p className="text-muted-foreground text-xs font-mono">
              {recipientsBadgeSlug}
            </p>
          ) : null}
          {recipientsError ? (
            <p className="text-destructive text-sm" role="alert">
              {recipientsError}
            </p>
          ) : null}
          {recipientsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground text-sm">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Loading recipients…
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Recipient</TableHead>
                  <TableHead>Granted</TableHead>
                  <TableHead className="text-right w-28"> </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(recipientsQuery.data?.data.length ?? 0) === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={3}
                      className="text-muted-foreground text-sm"
                    >
                      No active grants for this badge.
                    </TableCell>
                  </TableRow>
                ) : null}
                {recipientsQuery.data?.data.map((r) => (
                  <TableRow key={r.user_id}>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium">
                          {r.full_name?.trim() || r.email}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {r.email}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {r.granted_at
                        ? new Date(r.granted_at).toLocaleString()
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`workshop-badge-hub-recipient-revoke-${r.user_id}`}
                        disabled={revokeMutation.isPending}
                        onClick={() => {
                          setRecipientsError(null)
                          setRevokeUserId(r.user_id)
                          setRevokeReason("")
                        }}
                      >
                        Revoke
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {revokeUserId !== null ? (
            <div
              className="space-y-2 rounded-md border p-3"
              data-testid="workshop-badge-hub-recipients-revoke-panel"
            >
              <Label htmlFor="workshop-badge-hub-recipients-reason">
                Reason for revoke
              </Label>
              <Input
                id="workshop-badge-hub-recipients-reason"
                value={revokeReason}
                onChange={(e) => setRevokeReason(e.target.value)}
                placeholder="Required"
                data-testid="workshop-badge-hub-recipients-reason"
              />
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setRevokeUserId(null)
                    setRevokeReason("")
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  data-testid="workshop-badge-hub-recipients-revoke-confirm"
                  disabled={
                    revokeReason.trim().length === 0 ||
                    recipientsBadgeId === null ||
                    revokeMutation.isPending
                  }
                  onClick={() => {
                    if (
                      recipientsBadgeId === null ||
                      revokeUserId === null ||
                      revokeReason.trim().length === 0
                    )
                      return
                    setRecipientsError(null)
                    revokeMutation.mutate({
                      badgeId: recipientsBadgeId,
                      userId: revokeUserId,
                      reason: revokeReason.trim(),
                    })
                  }}
                >
                  {revokeMutation.isPending ? (
                    <>
                      <Loader2
                        className="mr-2 h-4 w-4 animate-spin"
                        aria-hidden
                      />
                      Revoking…
                    </>
                  ) : (
                    "Confirm revoke"
                  )}
                </Button>
              </div>
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              data-testid="workshop-badge-recipients-close"
              onClick={() => {
                setRecipientsBadgeId(null)
                setRecipientsBadgeSlug(null)
              }}
            >
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
