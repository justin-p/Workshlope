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
      try {
        await WorkshopSessionsService.enterWorkshopSession({ sessionId })
        const ticketRes = await WorkshopSessionsService.createWorkshopWsTicket({
          sessionId,
        })
        if (cancelled) return

        setPhase("ws_connecting")
        const apiBase = import.meta.env.VITE_API_URL as string
        const wsUrl = `${httpToWsBase(apiBase)}/api/v1/workshop/sessions/${sessionId}/ws`
        const ws = new WebSocket(wsUrl, ["ticket", ticketRes.ticket])
        wsRef.current = ws

        ws.onmessage = (ev) => {
          if (cancelled) return
          setLastEvent(String(ev.data))
          try {
            const msg = JSON.parse(String(ev.data)) as { type?: string }
            if (msg.type === "session.connected") {
              setPhase("ready")
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

      <div className="flex gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={phase !== "ready"}
          onClick={() => sendLiveStatus("busy")}
        >
          Mark busy
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={phase !== "ready"}
          onClick={() => sendLiveStatus("done")}
        >
          Mark done
        </Button>
      </div>

      {lastEvent ? (
        <pre
          data-testid="workshop-ws-last-raw"
          className="text-xs bg-muted p-3 rounded-md overflow-auto max-h-48"
        >
          {lastEvent}
        </pre>
      ) : null}
    </div>
  )
}
