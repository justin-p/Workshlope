import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"

import { ApiError, WorkshopSessionsService } from "@/client"
import { Button } from "@/components/ui/button"

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

/** Decode JWT payload segment (no verification — UI routing only). */
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
  const [phase, setPhase] = useState<
    "idle" | "entering" | "ws_connecting" | "ready" | "error"
  >("idle")
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [lastEvent, setLastEvent] = useState<string>("")
  const [lastAckEvent, setLastAckEvent] = useState<string>("")
  const [connectedRole, setConnectedRole] = useState<
    "participant" | "instructor" | null
  >(null)
  const [roomStatus, setRoomStatus] = useState<"live" | "paused">("live")
  const wsRef = useRef<WebSocket | null>(null)

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
        const apiBase = import.meta.env.VITE_API_URL as string
        const wsUrl = `${httpToWsBase(apiBase)}/api/v1/workshop/sessions/${sessionId}/ws`
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
            }
            if (typeof msg.type === "string" && msg.type.endsWith(".ack")) {
              setLastAckEvent(raw)
            }
            if (msg.type === "session.connected") {
              if (msg.role === "participant" || msg.role === "instructor") {
                setConnectedRole(msg.role)
              }
              setPhase("ready")
            }
            if (
              msg.type === "session.status_changed" &&
              (msg.status === "live" || msg.status === "paused")
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

  const instructorReady = phase === "ready" && connectedRole === "instructor"

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Workshop session</h1>
      <p className="text-muted-foreground text-sm">
        Session <code className="text-xs">{sessionId}</code>
      </p>

      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-sm text-muted-foreground">Realtime:</span>
        <span data-testid="workshop-ws-status" className="text-sm font-medium">
          {phase === "ready"
            ? "connected"
            : phase === "error"
              ? "error"
              : phase === "idle"
                ? "…"
                : "connecting"}
        </span>
      </div>

      {errorDetail ? (
        <p className="text-sm text-destructive" data-testid="workshop-error">
          {errorDetail}
        </p>
      ) : null}

      {connectedRole === "participant" ? (
        <div className="flex gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={phase !== "ready" || roomStatus !== "live"}
            onClick={() => sendLiveStatus("busy")}
          >
            Mark busy
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={phase !== "ready" || roomStatus !== "live"}
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
            disabled={!instructorReady || roomStatus !== "live"}
            onClick={() => sendWsJson({ type: "session.pause" })}
          >
            Pause room
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-instructor-resume"
            disabled={!instructorReady || roomStatus !== "paused"}
            onClick={() => sendWsJson({ type: "session.resume" })}
          >
            Resume room
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid="workshop-instructor-advance"
            disabled={!instructorReady || roomStatus !== "live"}
            onClick={() => sendWsJson({ type: "part.advance", part_index: 1 })}
          >
            Advance to part 1
          </Button>
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
