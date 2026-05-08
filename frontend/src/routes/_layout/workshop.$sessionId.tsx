import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"

import {
  ApiError,
  WorkshopLessonsService,
  WorkshopSessionsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"

/** Matches UUID v4 from `uuid.uuid4()` used for workshop sessions. */
const UUID_V4_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function httpToWsBase(httpBase: string): string {
  if (httpBase.startsWith("https://")) {
    return `wss://${httpBase.slice("https://".length)}`
  }
  if (httpBase.startsWith("http://")) {
    return `ws://${httpBase.slice("http://".length)}`
  }
  return httpBase
}

function formatTimerRemainingSeconds(totalSeconds: number): string {
  const clamped = Math.max(0, totalSeconds)
  const minutes = Math.floor(clamped / 60)
  const seconds = clamped % 60
  return `${minutes}:${String(seconds).padStart(2, "0")}`
}

function formatEventTimestamp(iso: string | null | undefined): string {
  if (!iso) return "unknown time"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return "unknown time"
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

/** Decode JWT payload segment (no verification - UI routing only). */
function decodeJwtPayloadJson(
  rawToken: string,
): Record<string, unknown> | null {
  const parts = rawToken.split(".")
  if (parts.length < 2) return null
  const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/")
  const pad = "=".repeat((4 - (b64.length % 4)) % 4)
  try {
    const json = atob(b64 + pad)
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return null
  }
}

async function createWorkshopWsTicketWithOptionalEnter(sessionId: string) {
  try {
    return await WorkshopSessionsService.createWorkshopWsTicket({
      sessionId,
    })
  } catch (e: unknown) {
    if (e instanceof ApiError && e.status === 403) {
      const body = e.body as { detail?: unknown } | undefined
      const detail = typeof body?.detail === "string" ? body.detail : undefined
      if (detail === "User must enter session first") {
        await WorkshopSessionsService.enterWorkshopSession({ sessionId })
        return await WorkshopSessionsService.createWorkshopWsTicket({
          sessionId,
        })
      }
    }
    throw e
  }
}

export const Route = createFileRoute("/_layout/workshop/$sessionId")({
  component: WorkshopSessionPage,
  head: () => ({
    meta: [{ title: "Workshop session" }],
  }),
})

function WorkshopSessionPage() {
  const { sessionId } = Route.useParams()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const uuidOk = UUID_V4_RE.test(sessionId)
  const detailQuery = useQuery({
    queryKey: ["workshopSessionDetail", sessionId],
    queryFn: () =>
      WorkshopSessionsService.readWorkshopSessionDetail({ sessionId }),
    enabled: uuidOk,
    retry: false,
    // Keep probing for recovery while content is marked unavailable.
    refetchInterval: (query) =>
      query.state.data?.lesson.lesson_content_available === false
        ? 5_000
        : false,
  })

  const lessonId = detailQuery.data?.lesson.id
  const detailView = detailQuery.data?.view
  const detail = detailQuery.data
  /** HTTP detail is instructor-first when user has both seats; WS still uses participant. */
  const userSeesTraineePrework =
    detail?.view === "participant" ||
    (detail?.view === "instructor" &&
      currentUser?.id !== undefined &&
      detail.participants.some((p) => p.user_id === currentUser.id))

  const myPrerequisitesQuery = useQuery({
    queryKey: ["workshopMyLessonPrerequisites", lessonId],
    queryFn: () =>
      WorkshopLessonsService.readMyLessonPrerequisites({ lessonId: lessonId! }),
    enabled:
      uuidOk &&
      detailQuery.isSuccess &&
      lessonId !== undefined &&
      userSeesTraineePrework,
    retry: false,
  })

  const aggregatesQuery = useQuery({
    queryKey: ["workshopPrerequisiteAggregates", lessonId, sessionId],
    queryFn: () =>
      WorkshopLessonsService.readLessonPrerequisiteAggregatesForSessionRoster({
        lessonId: lessonId!,
        sessionId,
      }),
    enabled:
      uuidOk &&
      detailQuery.isSuccess &&
      lessonId !== undefined &&
      detailView === "instructor",
    retry: false,
  })

  const gapsQuery = useQuery({
    queryKey: ["workshopPrerequisiteGaps", lessonId, sessionId],
    queryFn: () =>
      WorkshopLessonsService.readLessonPrerequisiteGapsForSessionRoster({
        lessonId: lessonId!,
        sessionId,
      }),
    enabled:
      uuidOk &&
      detailQuery.isSuccess &&
      lessonId !== undefined &&
      detailView === "instructor",
    retry: false,
  })

  const completePrerequisiteMutation = useMutation({
    mutationFn: ({
      lessonId: lid,
      prerequisiteId,
    }: {
      lessonId: string
      prerequisiteId: string
    }) =>
      WorkshopLessonsService.completeLessonPrerequisite({
        lessonId: lid,
        prerequisiteId,
      }),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["workshopMyLessonPrerequisites", variables.lessonId],
      })
    },
  })

  const timerQuery = useQuery({
    queryKey: ["workshopSessionTimer", sessionId],
    queryFn: () =>
      WorkshopSessionsService.readWorkshopSessionTimer({ sessionId }),
    enabled: uuidOk && detailView === "instructor",
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 1_000 : false,
  })

  const timerEventsQuery = useQuery({
    queryKey: ["workshopSessionTimerEvents", sessionId],
    queryFn: () =>
      WorkshopSessionsService.readWorkshopSessionTimerEvents({
        sessionId,
        limit: 5,
      }),
    enabled: uuidOk && detailView === "instructor",
    retry: false,
    refetchInterval: () =>
      timerQuery.data?.status === "running" ? 5_000 : false,
  })

  const startTimerMutation = useMutation({
    mutationFn: () =>
      WorkshopSessionsService.startWorkshopSessionTimer({
        sessionId,
        requestBody: { mode: "countdown" },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimer", sessionId],
      })
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimerEvents", sessionId],
      })
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    },
  })

  const extendTimerMutation = useMutation({
    mutationFn: () =>
      WorkshopSessionsService.extendWorkshopSessionTimer({
        sessionId,
        requestBody: { additional_seconds: timerExtendMinutes * 60 },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimer", sessionId],
      })
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimerEvents", sessionId],
      })
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    },
  })

  const pauseTimerMutation = useMutation({
    mutationFn: () =>
      WorkshopSessionsService.pauseWorkshopSessionTimer({ sessionId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimer", sessionId],
      })
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimerEvents", sessionId],
      })
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    },
  })

  const resumeTimerMutation = useMutation({
    mutationFn: () =>
      WorkshopSessionsService.resumeWorkshopSessionTimer({ sessionId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimer", sessionId],
      })
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimerEvents", sessionId],
      })
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    },
  })

  const stopTimerMutation = useMutation({
    mutationFn: () =>
      WorkshopSessionsService.stopWorkshopSessionTimer({ sessionId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimer", sessionId],
      })
      void queryClient.invalidateQueries({
        queryKey: ["workshopSessionTimerEvents", sessionId],
      })
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    },
  })

  const [phase, setPhase] = useState<
    "idle" | "entering" | "ws_connecting" | "ready" | "error"
  >("idle")
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [lastEvent, setLastEvent] = useState<string>("")
  const [lastAckEvent, setLastAckEvent] = useState<string>("")
  const [realtimePartIndex, setRealtimePartIndex] = useState<number | null>(
    null,
  )
  const [timerExtendMinutes, setTimerExtendMinutes] = useState<number>(5)
  const [connectedRole, setConnectedRole] = useState<
    "participant" | "instructor" | null
  >(null)
  const [roomStatus, setRoomStatus] = useState<"live" | "paused" | "ended">(
    "live",
  )
  const wsRef = useRef<WebSocket | null>(null)
  const wsSessionReadyRef = useRef(false)
  const wsStaleReconnectAttemptsRef = useRef(0)
  const [_wsReconnectNonce, setWsReconnectNonce] = useState(0)

  useEffect(() => {
    if (!UUID_V4_RE.test(sessionId)) {
      setPhase("error")
      setErrorDetail("Invalid session id")
      return
    }

    let cancelled = false

    async function connect() {
      setPhase("entering")
      setErrorDetail(null)
      setConnectedRole(null)
      setRoomStatus("live")
      setLastAckEvent("")
      setRealtimePartIndex(null)
      wsSessionReadyRef.current = false
      let reconnectingBecauseStaleGeneration = false
      try {
        const ticketRes =
          await createWorkshopWsTicketWithOptionalEnter(sessionId)
        if (cancelled) return

        const claims = decodeJwtPayloadJson(ticketRes.ticket)
        const roleClaim = claims?.role
        if (roleClaim !== "participant" && roleClaim !== "instructor") {
          setPhase("error")
          setErrorDetail("Invalid workshop ticket role")
          return
        }

        setPhase("ws_connecting")
        const rawBase = (
          import.meta.env.VITE_API_URL as string | undefined
        )?.trim()
        const apiHttpBase =
          rawBase !== undefined && rawBase !== ""
            ? rawBase
            : window.location.origin
        const wsUrl = `${httpToWsBase(apiHttpBase)}/api/v1/workshop/sessions/${sessionId}/ws`
        const ws = new WebSocket(wsUrl, ["ticket", ticketRes.ticket])
        wsRef.current = ws

        ws.onmessage = (ev) => {
          if (cancelled) return
          const raw = String(ev.data)
          setLastEvent(raw)
          try {
            const msg = JSON.parse(raw) as {
              type?: string
              role?: string
              status?: string
              detail?: string
              part_index?: number
            }
            if (
              msg.type === "error" &&
              msg.detail === "part_generation_stale" &&
              wsStaleReconnectAttemptsRef.current < 2
            ) {
              reconnectingBecauseStaleGeneration = true
              wsStaleReconnectAttemptsRef.current += 1
              setPhase("ws_connecting")
              setErrorDetail(
                "Session content changed. Reconnecting realtime...",
              )
              wsSessionReadyRef.current = false
              ws.close()
              setWsReconnectNonce((value) => value + 1)
              return
            }
            if (typeof msg.type === "string" && msg.type.endsWith(".ack")) {
              setLastAckEvent(raw)
            }
            if (
              (msg.type === "part.advance.ack" ||
                msg.type === "session.part_changed") &&
              typeof msg.part_index === "number" &&
              msg.part_index >= 0
            ) {
              setRealtimePartIndex(msg.part_index)
            }
            if (msg.type === "session.connected") {
              if (msg.role === "participant" || msg.role === "instructor") {
                setConnectedRole(msg.role)
              }
              wsStaleReconnectAttemptsRef.current = 0
              wsSessionReadyRef.current = true
              setPhase("ready")
            }
            if (
              msg.type === "session.status_changed" &&
              (msg.status === "live" ||
                msg.status === "paused" ||
                msg.status === "ended")
            ) {
              setRoomStatus(msg.status)
            }
          } catch {
            /* non-JSON frame */
          }
        }
        ws.onerror = () => {
          if (cancelled) return
          setPhase("error")
          setErrorDetail("WebSocket error")
        }
        ws.onclose = () => {
          if (cancelled) return
          wsRef.current = null
          if (reconnectingBecauseStaleGeneration) {
            return
          }
          if (!wsSessionReadyRef.current) {
            setPhase("error")
            setErrorDetail(
              "Realtime disconnected before the session was ready.",
            )
          }
        }
      } catch (e: unknown) {
        if (cancelled) return
        setPhase("error")
        if (e instanceof ApiError) {
          const body = e.body as { detail?: string } | undefined
          setErrorDetail(body?.detail ?? e.message)
        } else {
          setErrorDetail(e instanceof Error ? e.message : "Request failed")
        }
      }
    }

    void connect()

    return () => {
      cancelled = true
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [sessionId])

  const sendLiveStatus = (liveStatus: "busy" | "done") => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: "live_status", live_status: liveStatus }))
  }

  const sendWsJson = (payload: Record<string, unknown>) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify(payload))
  }

  const endSession = async () => {
    try {
      await WorkshopSessionsService.endWorkshopSession({ sessionId })
      setRoomStatus("ended")
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    }
  }

  const startSession = async () => {
    try {
      await WorkshopSessionsService.startWorkshopSession({ sessionId })
      // Force a clean reconnect path after scheduled->live transition.
      window.location.reload()
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
      } else {
        setErrorDetail(e instanceof Error ? e.message : "Request failed")
      }
    }
  }

  const instructorReady = phase === "ready" && connectedRole === "instructor"

  const overdueRequiredPrerequisites =
    myPrerequisitesQuery.data?.data.filter(
      (p) => p.required_flag && !p.is_completed,
    ) ?? []

  const requiredAggregateRows =
    aggregatesQuery.data?.data.filter((r) => r.prerequisite.required_flag) ?? []
  const timerStatus = timerQuery.data?.status ?? "inactive"
  const timerMode = timerQuery.data?.mode
  const timerElapsedSeconds = timerQuery.data?.elapsed_seconds
  const timerRemainingSeconds = timerQuery.data?.remaining_seconds
  const timerEvents = timerEventsQuery.data?.data ?? []
  const isPreworkGateError = errorDetail === "Required prerequisites incomplete"
  const participantRemainingRequiredCount = overdueRequiredPrerequisites.length
  const instructorBlockedTraineesCount = gapsQuery.data?.count ?? 0
  const currentPartIndex =
    realtimePartIndex ?? detailQuery.data?.session.current_part_index ?? 0
  const currentPart = detailQuery.data?.parts[currentPartIndex] ?? null
  const totalParts = detailQuery.data?.parts.length ?? 0
  const previousPartIndex = currentPartIndex - 1
  const nextPartIndex = currentPartIndex + 1
  const canReturnToPreviousPart = previousPartIndex >= 0
  const canAdvanceToNextPart = nextPartIndex < totalParts
  const lessonRepoHealth =
    detailQuery.data?.lesson.lesson_repo_health ?? "healthy"
  const showLessonSourceWarning = lessonRepoHealth !== "healthy"
  const lessonContentAvailable =
    detailQuery.data?.lesson.lesson_content_available ?? true
  const lessonContentIssue =
    detailQuery.data?.lesson.lesson_content_issue ?? null
  const canRunLiveDelivery = lessonContentAvailable
  const lessonContentIssueHint =
    lessonContentIssue === "lesson_missing"
      ? "This session is linked to a lesson record that no longer exists."
      : lessonContentIssue === "lesson_repo_missing"
        ? "The lesson source repository record is missing."
        : lessonContentIssue === "no_parts_synced"
          ? "No lesson parts are currently synced for this lesson."
          : null

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">
        {detailQuery.data?.lesson.title ?? "Workshop session"}
      </h1>
      <p className="text-muted-foreground text-sm">
        Session <code className="text-xs">{sessionId}</code>
        {detailQuery.data?.lesson.slug ? (
          <>
            {" "}
            · <code className="text-xs">{detailQuery.data.lesson.slug}</code>
          </>
        ) : null}
      </p>
      {showLessonSourceWarning ? (
        <Alert
          variant="default"
          data-testid="workshop-lesson-source-warning"
          className="border-amber-500/50 bg-amber-500/10"
        >
          <AlertTitle>Lesson source unavailable</AlertTitle>
          <AlertDescription>
            Source sync is currently degraded; workshop is using last synced
            lesson content.
          </AlertDescription>
        </Alert>
      ) : null}
      {!lessonContentAvailable ? (
        <Alert
          variant="destructive"
          data-testid="workshop-lesson-content-unavailable"
        >
          <AlertTitle>Lesson content unavailable</AlertTitle>
          <AlertDescription>
            {lessonContentIssueHint ??
              "No lesson parts are currently available for this session."}{" "}
            {lessonContentIssue ? `(${lessonContentIssue}) ` : ""}
            Sync lesson content before running this workshop.
          </AlertDescription>
          <div className="mt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="workshop-lesson-content-refresh"
              disabled={detailQuery.isFetching}
              onClick={() => {
                void detailQuery.refetch()
              }}
            >
              Retry lesson check
            </Button>
          </div>
        </Alert>
      ) : null}
      {detailView === "participant" ? (
        <p
          className="text-xs text-muted-foreground"
          data-testid="workshop-prework-header-count"
        >
          Required pre-work remaining: {participantRemainingRequiredCount}
        </p>
      ) : null}
      {detailView === "instructor" ? (
        <p
          className="text-xs text-muted-foreground"
          data-testid="workshop-prework-header-count"
        >
          Roster trainees blocked by required pre-work:{" "}
          {instructorBlockedTraineesCount}
        </p>
      ) : null}
      {currentPart ? (
        <section
          className="rounded-lg border bg-card p-4 space-y-3"
          data-testid="workshop-current-part"
        >
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-lg font-semibold">{currentPart.title}</h2>
            <span className="text-xs text-muted-foreground">
              Part {currentPart.ordering + 1} of{" "}
              {detailQuery.data?.parts.length ?? 0}
            </span>
          </div>
          <article
            className="workshop-markdown max-w-none"
            data-testid="workshop-current-part-body"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: server sends nh3-sanitized html.
            dangerouslySetInnerHTML={{ __html: currentPart.body_html ?? "" }}
          />
        </section>
      ) : null}

      {userSeesTraineePrework &&
      overdueRequiredPrerequisites.length > 0 &&
      !myPrerequisitesQuery.isFetching ? (
        <Alert
          variant="destructive"
          data-testid="workshop-prework-participant-banner"
        >
          <AlertTitle>Incomplete pre-work</AlertTitle>
          <AlertDescription>
            <span className="block mb-2">
              Finish these before class so you&apos;re ready to start.
            </span>
            <ul className="list-none space-y-2 pl-0">
              {overdueRequiredPrerequisites.map((p) => (
                <li
                  key={p.id}
                  className="flex flex-wrap items-start justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2"
                >
                  <span className="min-w-0 text-sm">
                    {p.url ? (
                      <a
                        href={p.url}
                        className="underline font-medium text-foreground"
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        {p.title}
                      </a>
                    ) : (
                      p.title
                    )}
                  </span>
                  {lessonId ? (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="shrink-0"
                      disabled={completePrerequisiteMutation.isPending}
                      data-testid="workshop-prework-mark-complete"
                      aria-label={`Mark "${p.title}" complete`}
                      onClick={() =>
                        completePrerequisiteMutation.mutate({
                          lessonId,
                          prerequisiteId: p.id,
                        })
                      }
                    >
                      Mark complete
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {detailView === "instructor" ? (
        <div
          className="rounded-lg border px-4 py-3 text-sm space-y-2 bg-card"
          data-testid="workshop-prework-instructor-panel"
        >
          <div className="font-medium">Pre-work (rostered trainees)</div>
          {aggregatesQuery.isLoading || gapsQuery.isLoading ? (
            <p className="text-muted-foreground">Loading pre-work snapshot…</p>
          ) : aggregatesQuery.isError ? (
            <p className="text-destructive text-xs">
              Could not load prerequisite aggregates for this roster.
            </p>
          ) : (aggregatesQuery.data?.data ?? []).length === 0 ? (
            <p className="text-muted-foreground">
              No lesson prerequisites are defined yet.
            </p>
          ) : (
            <>
              <p
                className="text-muted-foreground text-xs"
                data-testid="workshop-prework-instructor-gaps-count"
              >
                {gapsQuery.isError
                  ? "Could not load who still owes required pre-work."
                  : `${gapsQuery.data?.count ?? 0} trainee(s) still missing at least one required prerequisite.`}
              </p>
              {requiredAggregateRows.length === 0 ? (
                <p className="text-muted-foreground">
                  No required prerequisites to track across the roster.
                </p>
              ) : (
                <ul className="space-y-1 list-disc ml-5 text-muted-foreground">
                  {requiredAggregateRows.map((r) => (
                    <li key={r.prerequisite.id}>
                      <span className="text-foreground">
                        {r.prerequisite.title}
                      </span>
                      {": "}
                      {r.completed_count}/{r.roster_count} trainees done
                      {r.roster_count === 0 ? (
                        <span className="italic">
                          {" "}
                          - nobody on the roster yet
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-sm text-muted-foreground">Realtime:</span>
        <span data-testid="workshop-ws-status" className="text-sm font-medium">
          {phase === "ready"
            ? "connected"
            : phase === "error"
              ? isPreworkGateError
                ? "gated"
                : "error"
              : phase === "idle"
                ? "…"
                : "connecting"}
        </span>
      </div>

      {errorDetail && !isPreworkGateError ? (
        <p className="text-sm text-destructive" data-testid="workshop-error">
          {errorDetail}
        </p>
      ) : null}
      {isPreworkGateError ? (
        <Alert variant="destructive" data-testid="workshop-prework-gate-error">
          <AlertTitle>Pre-work required before joining live session</AlertTitle>
          <AlertDescription>
            Complete all required prerequisites, then reload or re-open this
            session to connect.
          </AlertDescription>
        </Alert>
      ) : null}
      {errorDetail === "Session not started yet" ? (
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            data-testid="workshop-instructor-start"
            onClick={() => void startSession()}
          >
            Start session
          </Button>
        </div>
      ) : null}

      {connectedRole === "participant" ? (
        <div className="flex gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={
              phase !== "ready" || roomStatus !== "live" || !canRunLiveDelivery
            }
            onClick={() => sendLiveStatus("busy")}
          >
            Mark busy
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={
              phase !== "ready" || roomStatus !== "live" || !canRunLiveDelivery
            }
            onClick={() => sendLiveStatus("done")}
          >
            Mark done
          </Button>
        </div>
      ) : null}

      {connectedRole === "instructor" ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-instructor-pause"
            disabled={
              !instructorReady || roomStatus !== "live" || !canRunLiveDelivery
            }
            onClick={() => sendWsJson({ type: "session.pause" })}
          >
            Pause room
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-instructor-resume"
            disabled={
              !instructorReady || roomStatus !== "paused" || !canRunLiveDelivery
            }
            onClick={() => sendWsJson({ type: "session.resume" })}
          >
            Resume room
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-instructor-back-part"
            disabled={
              !instructorReady ||
              roomStatus !== "live" ||
              !canRunLiveDelivery ||
              !canReturnToPreviousPart
            }
            onClick={() =>
              sendWsJson({
                type: "part.advance",
                part_index: previousPartIndex,
              })
            }
          >
            Back to part {previousPartIndex + 1}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-instructor-advance"
            disabled={
              !instructorReady ||
              roomStatus !== "live" ||
              !canRunLiveDelivery ||
              !canAdvanceToNextPart
            }
            onClick={() =>
              sendWsJson({ type: "part.advance", part_index: nextPartIndex })
            }
          >
            Advance to part {nextPartIndex + 1}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-timer-start"
            disabled={
              !instructorReady ||
              timerStatus !== "inactive" ||
              !canRunLiveDelivery ||
              startTimerMutation.isPending
            }
            onClick={() => startTimerMutation.mutate()}
          >
            Start part countdown
          </Button>
          <label className="text-xs text-muted-foreground self-center">
            Extend by (min)
            <input
              type="number"
              min={1}
              max={120}
              step={1}
              value={timerExtendMinutes}
              data-testid="workshop-timer-extend-minutes"
              className="ml-2 h-8 w-20 rounded border bg-background px-2 text-foreground"
              onChange={(event) => {
                const nextValue = Number.parseInt(event.target.value, 10)
                if (Number.isNaN(nextValue)) return
                setTimerExtendMinutes(Math.min(120, Math.max(1, nextValue)))
              }}
            />
          </label>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-timer-extend"
            disabled={
              !instructorReady ||
              timerStatus === "inactive" ||
              timerMode !== "countdown" ||
              !canRunLiveDelivery ||
              extendTimerMutation.isPending
            }
            onClick={() => extendTimerMutation.mutate()}
          >
            Extend +{timerExtendMinutes}m
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-timer-pause"
            disabled={
              !instructorReady ||
              timerStatus !== "running" ||
              !canRunLiveDelivery ||
              pauseTimerMutation.isPending
            }
            onClick={() => pauseTimerMutation.mutate()}
          >
            Pause timer
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-timer-resume"
            disabled={
              !instructorReady ||
              timerStatus !== "paused" ||
              !canRunLiveDelivery ||
              resumeTimerMutation.isPending
            }
            onClick={() => resumeTimerMutation.mutate()}
          >
            Resume timer
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-timer-stop"
            disabled={
              !instructorReady ||
              timerStatus === "inactive" ||
              !canRunLiveDelivery ||
              stopTimerMutation.isPending
            }
            onClick={() => stopTimerMutation.mutate()}
          >
            Stop timer
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            data-testid="workshop-instructor-end"
            disabled={
              !instructorReady || roomStatus === "ended" || !canRunLiveDelivery
            }
            onClick={() => void endSession()}
          >
            End session
          </Button>
          <span
            className="text-xs text-muted-foreground self-center"
            data-testid="workshop-timer-status"
          >
            Timer: {timerStatus}
            {timerMode ? ` (${timerMode})` : ""}
            {typeof timerRemainingSeconds === "number"
              ? ` (${formatTimerRemainingSeconds(timerRemainingSeconds)} left)`
              : typeof timerElapsedSeconds === "number"
                ? ` (${formatTimerRemainingSeconds(timerElapsedSeconds)} elapsed)`
                : ""}
          </span>
          <div
            className="w-full rounded-md border p-2 text-xs text-muted-foreground"
            data-testid="workshop-timer-events"
          >
            <div className="font-medium text-foreground mb-1">
              Recent timer events
            </div>
            {timerEventsQuery.isLoading ? (
              <p>Loading timer events...</p>
            ) : timerEvents.length === 0 ? (
              <p>No timer actions recorded yet.</p>
            ) : (
              <ul className="space-y-1">
                {timerEvents.map((event) => (
                  <li key={event.id} className="flex gap-2 items-center">
                    <span className="uppercase text-[10px] tracking-wide">
                      {event.action}
                    </span>
                    <span>{event.mode ?? "n/a"}</span>
                    <span>
                      {event.target_seconds
                        ? `${event.target_seconds}s`
                        : "countup"}
                    </span>
                    <span className="text-[10px] text-muted-foreground/80">
                      {formatEventTimestamp(event.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : null}

      {lastEvent ? (
        <pre
          data-testid="workshop-ws-last-raw"
          className="text-xs bg-muted p-3 rounded-md overflow-auto max-h-48"
        >
          {lastEvent}
        </pre>
      ) : null}
      {lastAckEvent ? (
        <pre
          data-testid="workshop-ws-last-ack"
          className="text-xs bg-muted p-3 rounded-md overflow-auto max-h-48"
        >
          {lastAckEvent}
        </pre>
      ) : null}
    </div>
  )
}
