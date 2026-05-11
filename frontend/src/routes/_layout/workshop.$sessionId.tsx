import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import {
  ApiError,
  WorkshopLessonsService,
  type WorkshopSessionsReadWorkshopSessionDetailResponse,
  WorkshopSessionsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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
  const sessionInLobby =
    Boolean(detailQuery.isSuccess) && detail?.session.status === "scheduled"

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
  const addTraineeMutation = useMutation({
    mutationFn: (userId: string) =>
      WorkshopSessionsService.upsertWorkshopSessionMember({
        sessionId,
        requestBody: { user_id: userId, role: "participant" },
      }),
    onSuccess: async () => {
      setErrorDetail(null)
      setNewTraineeUserId("")
      await Promise.all([
        detailQuery.refetch(),
        gapsQuery.refetch(),
        aggregatesQuery.refetch(),
      ])
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

  const removeTraineeMutation = useMutation({
    mutationFn: (userId: string) =>
      WorkshopSessionsService.removeWorkshopSessionParticipant({
        sessionId,
        userId,
      }),
    onSuccess: async () => {
      setErrorDetail(null)
      setRemoveParticipantUserId(null)
      await Promise.all([
        detailQuery.refetch(),
        gapsQuery.refetch(),
        aggregatesQuery.refetch(),
      ])
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
  const [newTraineeUserId, setNewTraineeUserId] = useState<string>("")
  const ROSTER_PICKER_LIMIT = 25
  const ROSTER_PICKER_DEBOUNCE_MS = 350
  const [rosterPickerSearch, setRosterPickerSearch] = useState("")
  const [rosterPickerQuery, setRosterPickerQuery] = useState("")
  const [rosterPickerSkip, setRosterPickerSkip] = useState(0)
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(
    () => new Set(),
  )
  const [pickerNotice, setPickerNotice] = useState<string | null>(null)
  const [removeParticipantUserId, setRemoveParticipantUserId] = useState<
    string | null
  >(null)
  const [isAddingSelected, setIsAddingSelected] = useState(false)
  const [_pickerAddError, setPickerAddError] = useState<string | null>(null)
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
    const t = window.setTimeout(
      () => setRosterPickerQuery(rosterPickerSearch.trim()),
      ROSTER_PICKER_DEBOUNCE_MS,
    )
    return () => window.clearTimeout(t)
  }, [rosterPickerSearch])

  useEffect(() => {
    setRosterPickerSkip(0)
    setSelectedUserIds(new Set())
    if (rosterPickerQuery.trim().length > 0) {
      setPickerNotice("Selection cleared — search changed")
    } else {
      setPickerNotice("Selection cleared")
    }
    const t = window.setTimeout(() => setPickerNotice(null), 2500)
    return () => window.clearTimeout(t)
  }, [rosterPickerQuery])

  const rosterUserPickerQuery = useQuery({
    queryKey: [
      "workshopRosterUserPicker",
      sessionId,
      rosterPickerQuery,
      rosterPickerSkip,
      ROSTER_PICKER_LIMIT,
    ],
    queryFn: () =>
      WorkshopSessionsService.readWorkshopSessionRosterUserPicker({
        sessionId,
        q: rosterPickerQuery.trim().length > 0 ? rosterPickerQuery : undefined,
        skip: rosterPickerSkip,
        limit: ROSTER_PICKER_LIMIT,
      }),
    enabled: uuidOk && detailView === "instructor",
    retry: false,
  })

  const addSelectedChunkMutation = useMutation({
    mutationFn: (uids: string[]) =>
      WorkshopSessionsService.batchUpsertWorkshopSessionParticipants({
        sessionId,
        requestBody: { user_ids: uids },
      }),
  })

  // biome-ignore lint/correctness/useExhaustiveDependencies: reconnect only when `session.status` changes; listing full `detailQuery.data` reconnects on roster-only cache patches.
  useEffect(() => {
    if (!UUID_V4_RE.test(sessionId)) {
      setPhase("error")
      setErrorDetail("Invalid session id")
      return () => {}
    }

    let cancelled = false

    if (!detailQuery.isSuccess || detailQuery.data === undefined) {
      return () => {
        cancelled = true
        wsRef.current?.close()
        wsRef.current = null
      }
    }

    const sessionStatus = detailQuery.data.session.status
    if (
      sessionStatus !== "live" &&
      sessionStatus !== "paused" &&
      sessionStatus !== "scheduled"
    ) {
      setPhase("idle")
      setErrorDetail(null)
      setConnectedRole(null)
      wsRef.current?.close()
      wsRef.current = null
      return () => {
        cancelled = true
        wsRef.current?.close()
        wsRef.current = null
      }
    }

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
              user_id?: string
              live_status?: string
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
              const nextStatus = msg.status as "live" | "paused" | "ended"
              setRoomStatus(nextStatus)
              // Only patch HTTP-shaped detail when leaving the scheduled lobby or
              // when the session ends. live↔paused is carried by `roomStatus` alone;
              // mirroring pause into the query cache re-triggers the WS effect deps
              // and tears down the socket while `instructorReady` is briefly false.
              queryClient.setQueryData<
                WorkshopSessionsReadWorkshopSessionDetailResponse | undefined
              >(["workshopSessionDetail", sessionId], (cached) => {
                if (!cached) return cached
                const cur = cached.session.status
                if (cur !== "scheduled" || nextStatus !== "live") return cached
                return {
                  ...cached,
                  session: { ...cached.session, status: "live" },
                }
              })
            }
            if (msg.type === "participant.live_status") {
              const userId = msg.user_id
              const nextLiveStatus = msg.live_status
              if (
                typeof userId === "string" &&
                userId.length > 0 &&
                typeof nextLiveStatus === "string" &&
                nextLiveStatus.length > 0
              ) {
                queryClient.setQueryData<
                  WorkshopSessionsReadWorkshopSessionDetailResponse | undefined
                >(["workshopSessionDetail", sessionId], (cached) => {
                  if (!cached || cached.view !== "instructor") return cached
                  return {
                    ...cached,
                    participants: cached.participants.map((p) =>
                      p.user_id === userId
                        ? { ...p, live_status: nextLiveStatus }
                        : p,
                    ),
                  }
                })
              }
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
  }, [
    sessionId,
    queryClient,
    detailQuery.isSuccess,
    detailQuery.data?.session.status,
  ])

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
      await detailQuery.refetch()
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
  const rosterParticipants =
    detailQuery.data?.view === "instructor" ? detailQuery.data.participants : []
  const removeDialogParticipant =
    removeParticipantUserId === null
      ? undefined
      : rosterParticipants.find((p) => p.user_id === removeParticipantUserId)
  const lessonContentIssueHint =
    lessonContentIssue === "lesson_missing"
      ? "This session is linked to a lesson record that no longer exists."
      : lessonContentIssue === "lesson_repo_missing"
        ? "The lesson source repository record is missing."
        : lessonContentIssue === "no_parts_synced"
          ? "No lesson parts are currently synced for this lesson."
          : null

  const handleAddSelectedToRoster = async () => {
    const ids = Array.from(selectedUserIds)
    if (ids.length === 0) return

    setPickerAddError(null)
    setIsAddingSelected(true)
    try {
      const CHUNK_SIZE = 100
      const mergedResults: Array<{
        status: string
      }> = []

      for (let i = 0; i < ids.length; i += CHUNK_SIZE) {
        const chunk = ids.slice(i, i + CHUNK_SIZE)
        const res = await addSelectedChunkMutation.mutateAsync(chunk)
        mergedResults.push(...res.results)
      }

      await Promise.all([
        detailQuery.refetch(),
        gapsQuery.refetch(),
        aggregatesQuery.refetch(),
      ])

      setSelectedUserIds(new Set())

      const added = mergedResults.filter((r) => r.status === "added").length
      const already = mergedResults.filter((r) => r.status === "already").length
      const notFound = mergedResults.filter(
        (r) => r.status === "not_found",
      ).length
      const errored = mergedResults.filter((r) => r.status === "error").length

      const bits = [`Added ${added} trainee${added === 1 ? "" : "s"}`]
      if (already > 0) bits.push(`Already on roster: ${already}`)
      if (notFound > 0) bits.push(`Not found: ${notFound}`)
      if (errored > 0) bits.push(`Errors: ${errored}`)

      setPickerNotice(bits.join(" · "))
      window.setTimeout(() => setPickerNotice(null), 4000)
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setPickerAddError(body?.detail ?? e.message)
      } else {
        setPickerAddError(e instanceof Error ? e.message : "Request failed")
      }
    } finally {
      setIsAddingSelected(false)
    }
  }

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
      {sessionInLobby ? (
        <Alert
          variant="default"
          className="border-primary/25 bg-muted/50"
          data-testid="workshop-session-lobby"
        >
          <AlertTitle>Session not started</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              {detailView === "instructor"
                ? "Start the workshop when you are ready. Live controls and lesson delivery unlock after you start."
                : "The instructor has not started this workshop yet. You can complete required pre-work below while you wait."}
            </p>
            {detailView === "instructor" ? (
              <Button
                type="button"
                size="sm"
                data-testid="workshop-instructor-start"
                onClick={() => void startSession()}
              >
                Start session
              </Button>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
      {currentPart && !sessionInLobby ? (
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
      {detailView === "instructor" ? (
        <div
          className="rounded-lg border px-4 py-3 text-sm space-y-2 bg-card"
          data-testid="workshop-roster-panel"
        >
          <div className="font-medium">
            Trainee roster ({rosterParticipants.length})
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-end gap-2 justify-between">
              <label
                htmlFor="workshop-roster-user-picker-search"
                className="text-xs text-muted-foreground"
              >
                Find users
                <div className="mt-1 flex items-center gap-2">
                  <Input
                    type="text"
                    value={rosterPickerSearch}
                    onChange={(e) => setRosterPickerSearch(e.target.value)}
                    data-testid="workshop-roster-user-picker-search"
                    id="workshop-roster-user-picker-search"
                    placeholder="Search by full name or email"
                    className="w-[360px]"
                  />
                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 px-2"
                      data-testid="workshop-roster-user-picker-page-prev"
                      disabled={rosterPickerSkip <= 0}
                      onClick={() =>
                        setRosterPickerSkip((s) =>
                          Math.max(0, s - ROSTER_PICKER_LIMIT),
                        )
                      }
                    >
                      Prev
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 px-2"
                      data-testid="workshop-roster-user-picker-page-next"
                      disabled={
                        (rosterUserPickerQuery.data?.count ?? 0) <=
                        rosterPickerSkip + ROSTER_PICKER_LIMIT
                      }
                      onClick={() =>
                        setRosterPickerSkip((s) => s + ROSTER_PICKER_LIMIT)
                      }
                    >
                      Next
                    </Button>
                  </div>
                </div>
              </label>
            </div>

            {pickerNotice ? (
              <p
                className="text-xs text-muted-foreground"
                data-testid="workshop-roster-picker-notice"
              >
                {pickerNotice}
              </p>
            ) : null}

            {rosterUserPickerQuery.isError ? (
              <Alert
                variant="destructive"
                data-testid="workshop-roster-user-picker-error"
              >
                <AlertTitle>Could not load users</AlertTitle>
                <AlertDescription>
                  {rosterUserPickerQuery.error instanceof ApiError
                    ? ((
                        rosterUserPickerQuery.error.body as
                          | {
                              detail?: string
                            }
                          | undefined
                      )?.detail ?? rosterUserPickerQuery.error.message)
                    : rosterUserPickerQuery.error instanceof Error
                      ? rosterUserPickerQuery.error.message
                      : "Request failed"}
                </AlertDescription>
              </Alert>
            ) : null}

            {rosterUserPickerQuery.isLoading ? (
              <p className="text-xs text-muted-foreground">Loading users…</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[44px]" scope="col">
                      <span className="sr-only">Select</span>
                    </TableHead>
                    <TableHead className="w-[120px]" scope="col">
                      Type
                    </TableHead>
                    <TableHead scope="col">Email</TableHead>
                    <TableHead scope="col">Full name</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody data-testid="workshop-roster-user-picker-table">
                  {(rosterUserPickerQuery.data?.data ?? []).length ? (
                    (rosterUserPickerQuery.data?.data ?? []).map((row) => {
                      const onRoster = rosterParticipants.some(
                        (p) => p.user_id === row.user_id,
                      )
                      const disabled = onRoster || !row.is_active
                      const selected = selectedUserIds.has(row.user_id)
                      const typeBadges: React.ReactNode[] = []
                      if (row.is_superuser) {
                        typeBadges.push(
                          <Badge key="superuser" variant="secondary">
                            Superuser
                          </Badge>,
                        )
                      }
                      if (row.is_instructor) {
                        typeBadges.push(
                          <Badge key="instructor" variant="outline">
                            Instructor
                          </Badge>,
                        )
                      }
                      if (typeBadges.length === 0) {
                        typeBadges.push(
                          <Badge key="trainee" variant="outline">
                            Trainee
                          </Badge>,
                        )
                      }

                      return (
                        <TableRow key={row.user_id}>
                          <TableCell>
                            <Checkbox
                              checked={selected}
                              disabled={disabled}
                              aria-label={`Select ${row.email}`}
                              onCheckedChange={(checked) => {
                                if (typeof checked !== "boolean") return
                                setSelectedUserIds((prev) => {
                                  const next = new Set(prev)
                                  if (checked) next.add(row.user_id)
                                  else next.delete(row.user_id)
                                  return next
                                })
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {typeBadges}
                              {!row.is_active ? (
                                <Badge
                                  variant="destructive"
                                  className="opacity-80"
                                  title="Account inactive"
                                >
                                  Inactive
                                </Badge>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell
                            className={
                              !row.is_active
                                ? "text-muted-foreground"
                                : undefined
                            }
                          >
                            {row.email}
                          </TableCell>
                          <TableCell
                            className={
                              !row.is_active
                                ? "text-muted-foreground"
                                : undefined
                            }
                          >
                            {row.full_name ?? "—"}
                          </TableCell>
                        </TableRow>
                      )
                    })
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={4}
                        className="h-24 text-center text-muted-foreground"
                      >
                        No users found.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant={selectedUserIds.size === 0 ? "outline" : "default"}
                data-testid="workshop-roster-add-selected"
                disabled={
                  selectedUserIds.size === 0 ||
                  isAddingSelected ||
                  !canRunLiveDelivery
                }
                onClick={() => void handleAddSelectedToRoster()}
              >
                {isAddingSelected
                  ? "Adding..."
                  : `Add ${selectedUserIds.size} selected`}
              </Button>
              {selectedUserIds.size > 0 ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  data-testid="workshop-roster-clear-selection"
                  onClick={() => setSelectedUserIds(new Set())}
                >
                  Clear selection
                </Button>
              ) : null}
            </div>

            <div className="mt-4 flex flex-wrap items-end gap-2 border-t pt-4">
              <div className="flex min-w-0 flex-col gap-1">
                <Label
                  htmlFor="workshop-add-trainee-user-id"
                  className="text-xs font-normal text-muted-foreground"
                >
                  Paste user ID
                </Label>
                <Input
                  id="workshop-add-trainee-user-id"
                  type="text"
                  value={newTraineeUserId}
                  data-testid="workshop-add-trainee-user-id"
                  className="h-8 w-[min(100%,340px)] sm:w-[340px]"
                  placeholder="UUID (user_id)"
                  onChange={(event) => setNewTraineeUserId(event.target.value)}
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                data-testid="workshop-add-trainee-submit"
                disabled={
                  !newTraineeUserId.trim() ||
                  addTraineeMutation.isPending ||
                  !canRunLiveDelivery
                }
                onClick={() =>
                  addTraineeMutation.mutate(newTraineeUserId.trim())
                }
              >
                {addTraineeMutation.isPending ? "Adding..." : "Add trainee"}
              </Button>
            </div>

            {rosterParticipants.length === 0 ? (
              <p
                className="text-xs text-muted-foreground"
                data-testid="workshop-roster-empty"
              >
                No trainees on roster yet.
              </p>
            ) : (
              <ul
                className="space-y-1 text-xs"
                data-testid="workshop-roster-list"
              >
                {rosterParticipants.map((participant) => (
                  <li
                    key={participant.user_id}
                    className="text-muted-foreground flex flex-wrap items-center justify-between gap-2"
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      {participant.avatar_url ? (
                        <img
                          src={participant.avatar_url}
                          alt=""
                          className="size-5 shrink-0 rounded-full"
                        />
                      ) : null}
                      <span className="min-w-0 truncate">
                        {participant.full_name ?? participant.email}{" "}
                        <span className="text-xs text-muted-foreground">
                          ({participant.email})
                        </span>{" "}
                        · {participant.live_status}
                      </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge
                        variant={
                          participant.live_status === "done"
                            ? "default"
                            : "outline"
                        }
                        data-testid={`workshop-roster-live-status-${participant.user_id}`}
                      >
                        {participant.live_status}
                      </Badge>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-8 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        aria-label={`Remove ${participant.email} from roster`}
                        data-testid={`workshop-roster-remove-trainee-${participant.user_id}`}
                        disabled={
                          removeTraineeMutation.isPending || !canRunLiveDelivery
                        }
                        onClick={() =>
                          setRemoveParticipantUserId(participant.user_id)
                        }
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <Dialog
              open={removeParticipantUserId !== null}
              onOpenChange={(open) => {
                if (!open) setRemoveParticipantUserId(null)
              }}
            >
              <DialogContent showCloseButton>
                <DialogHeader>
                  <DialogTitle>Remove from roster?</DialogTitle>
                  <DialogDescription>
                    {removeDialogParticipant
                      ? `Remove ${removeDialogParticipant.full_name ?? removeDialogParticipant.email} (${removeDialogParticipant.email}) from this session roster. They can be added again later.`
                      : "Remove this trainee from the session roster."}
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setRemoveParticipantUserId(null)}
                    disabled={removeTraineeMutation.isPending}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    data-testid="workshop-roster-remove-confirm"
                    disabled={
                      removeParticipantUserId === null ||
                      removeTraineeMutation.isPending
                    }
                    onClick={() => {
                      if (removeParticipantUserId === null) return
                      removeTraineeMutation.mutate(removeParticipantUserId)
                    }}
                  >
                    {removeTraineeMutation.isPending ? "Removing…" : "Remove"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-sm text-muted-foreground">Realtime:</span>
        <span data-testid="workshop-ws-status" className="text-sm font-medium">
          {sessionInLobby && phase !== "ready"
            ? "waiting for start"
            : phase === "ready"
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

      {detailView === "instructor" ? (
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
