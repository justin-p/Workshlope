import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  type ComponentProps,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import type { WorkshopSessionListItem } from "@/client"
import { ApiError, WorkshopSessionsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

function httpToWsBase(httpBase: string): string {
  if (httpBase.startsWith("https://")) {
    return `wss://${httpBase.slice("https://".length)}`
  }
  if (httpBase.startsWith("http://")) {
    return `ws://${httpBase.slice("http://".length)}`
  }
  return httpBase
}

function apiErrorDetail(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  const body = error.body as { detail?: unknown } | undefined
  const d = body?.detail
  return typeof d === "string" ? d : undefined
}

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
  description = "Sessions where you have a roster seat - open to jump into /workshop (no peer list here).",
  workshopsHubLink,
}: {
  className?: string
  heading?: string
  description?: string
  /** Instructor / admin: link from card header to the workshops hub route */
  workshopsHubLink?: boolean
}) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [blockedOnly, setBlockedOnly] = useState(false)
  const reconnectAttemptRef = useRef(0)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["workshopSessionsForUser"],
    queryFn: () =>
      WorkshopSessionsService.readWorkshopSessionsForUser({
        skip: 0,
        limit: 50,
      }),
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false
      return failureCount < 3
    },
  })

  const detail = isError ? apiErrorDetail(error) : undefined
  const isUserAccount404 =
    error instanceof ApiError &&
    error.status === 404 &&
    detail === "User not found"
  /** API returns 200 with count 0 for an empty roster; 404 usually means mis-routed client or static host, not "no rows". */
  const showEmptyRosterCopy =
    (data !== undefined && data.count === 0) ||
    (isError &&
      error instanceof ApiError &&
      error.status === 404 &&
      !isUserAccount404)
  const showWorkshopQueryError = isError && !showEmptyRosterCopy
  useEffect(() => {
    if (!user) return

    let cancelled = false
    let socket: WebSocket | null = null
    let reconnectTimer: number | undefined

    const clearReconnect = () => {
      if (reconnectTimer !== undefined) {
        clearTimeout(reconnectTimer)
        reconnectTimer = undefined
      }
    }

    const scheduleReconnect = () => {
      if (cancelled) return
      reconnectAttemptRef.current += 1
      const delay = Math.min(
        30_000,
        1000 * 2 ** Math.min(reconnectAttemptRef.current, 5),
      )
      clearReconnect()
      reconnectTimer = window.setTimeout(() => {
        void connect()
      }, delay)
    }

    async function connect() {
      clearReconnect()
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        if (socket.readyState === WebSocket.OPEN) {
          return
        }
        socket.close()
        socket = null
      }
      try {
        const ticketRes =
          await WorkshopSessionsService.createUserWorkshopFeedWsTicket()
        if (cancelled) return

        const rawBase = (
          import.meta.env.VITE_API_URL as string | undefined
        )?.trim()
        const apiHttpBase =
          rawBase !== undefined && rawBase !== ""
            ? rawBase
            : window.location.origin
        const wsUrl = `${httpToWsBase(apiHttpBase)}/api/v1/workshop/sessions/user-workshop-feed/ws`
        socket = new WebSocket(wsUrl, ["ticket", ticketRes.ticket])

        socket.onopen = () => {
          reconnectAttemptRef.current = 0
        }

        socket.onmessage = (ev) => {
          try {
            const msg = JSON.parse(String(ev.data)) as { type?: string }
            if (msg.type === "workshop_sessions_list_changed") {
              void queryClient.invalidateQueries({
                queryKey: ["workshopSessionsForUser"],
              })
            }
          } catch {
            /* ignore non-JSON */
          }
        }

        socket.onclose = () => {
          socket = null
          if (!cancelled) scheduleReconnect()
        }
      } catch (e) {
        if (cancelled) return
        if (e instanceof ApiError && e.status === 401) {
          return
        }
        scheduleReconnect()
      }
    }

    void connect()

    const onVisible = () => {
      if (document.visibilityState !== "visible" || cancelled) return
      if (!socket || socket.readyState === WebSocket.CLOSED) {
        void connect()
      }
    }
    document.addEventListener("visibilitychange", onVisible)

    return () => {
      cancelled = true
      clearReconnect()
      document.removeEventListener("visibilitychange", onVisible)
      socket?.close()
    }
  }, [user, queryClient])
  const totalBlockedTrainees =
    data?.data.reduce(
      (sum, row) => sum + (row.blocked_required_prereq_count ?? 0),
      0,
    ) ?? 0
  const blockedRows =
    data?.data
      .filter((row) => (row.blocked_required_prereq_count ?? 0) > 0)
      .sort(
        (a, b) =>
          (b.blocked_required_prereq_count ?? 0) -
          (a.blocked_required_prereq_count ?? 0),
      ) ?? []
  const mostBlockedSession = blockedRows[0] ?? null
  const blockedSessionRatio =
    data && data.count > 0 ? `${blockedRows.length}/${data.count}` : "0/0"
  const visibleRows = useMemo(() => {
    if (!data?.data) return []
    if (!blockedOnly) return data.data
    return data.data.filter(
      (row) => (row.blocked_required_prereq_count ?? 0) > 0,
    )
  }, [blockedOnly, data?.data])

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
        {showWorkshopQueryError ? (
          <p className="text-destructive text-sm">
            {isUserAccount404
              ? "Your account was not found. Try signing out and back in."
              : ((error as Error)?.message ?? "Could not load sessions")}
          </p>
        ) : null}
        {showEmptyRosterCopy ? (
          <p className="text-muted-foreground text-sm">
            No workshops yet - you'll see sessions once you're on a roster.
          </p>
        ) : null}
        {data && data.count > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p
              className="text-muted-foreground text-xs"
              data-testid="workshop-cards-total-blocked"
            >
              Total blocked trainees: {totalBlockedTrainees}
            </p>
            <button
              type="button"
              className="text-primary text-xs underline underline-offset-4"
              data-testid="workshop-cards-blocked-only-toggle"
              onClick={() => setBlockedOnly((prev) => !prev)}
            >
              {blockedOnly ? "Show all sessions" : "Show blocked only"}
            </button>
          </div>
        ) : null}
        {blockedRows.length > 0 ? (
          <div
            className="rounded-md border border-amber-300/60 bg-amber-50/60 px-3 py-2 dark:border-amber-700/70 dark:bg-amber-950/20"
            data-testid="workshop-blocked-drilldown"
          >
            <p className="text-xs font-medium">Blocked sessions</p>
            <ul className="mt-1 space-y-1">
              {blockedRows.map((row) => (
                <li
                  key={`blocked-${row.id}`}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="truncate">{row.lesson_title}</span>
                  <span className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline">
                      {(row.blocked_required_prereq_count ?? 0).toString()}{" "}
                      blocked
                    </Badge>
                    <Link
                      to="/workshop/$sessionId"
                      params={{ sessionId: row.id }}
                      className="text-primary underline underline-offset-4"
                    >
                      Open
                    </Link>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {blockedRows.length > 0 && mostBlockedSession ? (
          <div
            className="rounded-md border px-3 py-2 text-xs bg-card"
            data-testid="workshop-blocked-analytics"
          >
            <p className="font-medium">Blocked prerequisite analytics</p>
            <p
              className="text-muted-foreground mt-1"
              data-testid="workshop-blocked-analytics-ratio"
            >
              Sessions impacted: {blockedSessionRatio}
            </p>
            <p
              className="text-muted-foreground"
              data-testid="workshop-blocked-analytics-most-blocked"
            >
              Most blocked session: {mostBlockedSession.lesson_title} (
              {mostBlockedSession.blocked_required_prereq_count ?? 0} blocked)
            </p>
          </div>
        ) : null}
        {data && data.data.length > 0 ? (
          <ul className="divide-border divide-y rounded-lg border">
            {visibleRows.map((row) => (
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
                    {row.my_role !== "participant" ? (
                      <Badge
                        variant="outline"
                        data-testid={`workshop-card-blocked-count-${row.id}`}
                      >
                        Blocked: {row.blocked_required_prereq_count ?? 0}
                      </Badge>
                    ) : null}
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
        {data && data.data.length > 0 && visibleRows.length === 0 ? (
          <p
            className="text-muted-foreground text-xs"
            data-testid="workshop-cards-no-blocked"
          >
            No sessions currently blocked by required pre-work.
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
