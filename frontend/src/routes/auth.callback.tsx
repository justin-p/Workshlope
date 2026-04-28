import { useMutation } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef } from "react"

import { OauthService } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { Button } from "@/components/ui/button"

interface CallbackSearch {
  bridge_token?: string
  error?: string
}

export const Route = createFileRoute("/auth/callback")({
  component: AuthCallback,
  validateSearch: (search: Record<string, unknown>): CallbackSearch => ({
    bridge_token:
      typeof search.bridge_token === "string" ? search.bridge_token : undefined,
    error: typeof search.error === "string" ? search.error : undefined,
  }),
  head: () => ({
    meta: [{ title: "Signing in - FastAPI Template" }],
  }),
})

function AuthCallback() {
  const { bridge_token, error } = Route.useSearch()
  const navigate = useNavigate()
  const startedRef = useRef(false)

  const bridgeMutation = useMutation({
    mutationFn: (input: { bridge_token: string }) =>
      OauthService.bridgeLogin({
        requestBody: { bridge_token: input.bridge_token },
      }),
    onSuccess: (data) => {
      if (data.status === "signed_in" && data.access_token) {
        localStorage.setItem("access_token", data.access_token)
        navigate({ to: "/" })
      }
    },
  })

  useEffect(() => {
    if (startedRef.current) return
    if (!bridge_token || error) return
    startedRef.current = true
    bridgeMutation.mutate({ bridge_token })
  }, [bridge_token, error, bridgeMutation])

  const isPending =
    bridgeMutation.data?.status === "pending_approval" &&
    !bridgeMutation.isError

  const failureDetail =
    !isPending &&
    (error ||
      (bridgeMutation.isError ? extractDetail(bridgeMutation.error) : null) ||
      (!bridge_token ? "Missing bridge token from Auth.js" : null))

  return (
    <AuthLayout>
      <div className="flex flex-col gap-6 text-center">
        {isPending ? (
          <>
            <h1 className="text-2xl font-bold">Awaiting admin approval</h1>
            <p
              data-testid="github-pending-approval"
              className="text-sm text-muted-foreground"
            >
              Your GitHub sign-in has been received. An administrator must
              approve your account before you can sign in. You will be able to
              sign in with GitHub once approved.
            </p>
            <Button onClick={() => navigate({ to: "/login" })}>
              Back to login
            </Button>
          </>
        ) : failureDetail ? (
          <>
            <h1 className="text-2xl font-bold">Signing you in...</h1>
            <p
              data-testid="github-login-error"
              className="text-sm text-destructive"
            >
              {failureDetail}
            </p>
            <Button onClick={() => navigate({ to: "/login" })}>
              Back to login
            </Button>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold">Signing you in...</h1>
            <p className="text-sm text-muted-foreground">
              Exchanging your GitHub identity for a session.
            </p>
          </>
        )}
      </div>
    </AuthLayout>
  )
}

function extractDetail(err: unknown): string {
  if (err && typeof err === "object") {
    const body = (err as { body?: { detail?: unknown } }).body
    const detail = body?.detail
    if (typeof detail === "string") return detail
    const message = (err as { message?: unknown }).message
    if (typeof message === "string" && message) return message
  }
  return "Sign-in failed"
}
