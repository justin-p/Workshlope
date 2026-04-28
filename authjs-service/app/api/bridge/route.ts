import { NextRequest, NextResponse } from "next/server"

import { auth } from "@/auth"
import { signBridgeToken } from "@/lib/bridge-token"

const FRONTEND_CALLBACK_URL =
  process.env.FRONTEND_CALLBACK_URL ?? "http://localhost:5173/auth/callback"

function resolveTargetUrl(callbackUrl: string | null): URL {
  // Always default to the frontend callback page; ignore externally supplied
  // callbacks that don't share the configured frontend origin to avoid open
  // redirects.
  if (!callbackUrl) return new URL(FRONTEND_CALLBACK_URL)
  try {
    const candidate = new URL(callbackUrl)
    const expected = new URL(FRONTEND_CALLBACK_URL)
    if (candidate.origin === expected.origin) {
      return candidate.pathname.startsWith("/auth/callback")
        ? candidate
        : new URL(FRONTEND_CALLBACK_URL)
    }
  } catch {
    /* fall through */
  }
  return new URL(FRONTEND_CALLBACK_URL)
}

export async function GET(req: NextRequest) {
  const session = await auth()
  const target = resolveTargetUrl(req.nextUrl.searchParams.get("callbackUrl"))

  if (!session || !session.providerAccountId) {
    target.searchParams.set("error", "not_authenticated")
    return NextResponse.redirect(target)
  }

  try {
    const bridgeToken = await signBridgeToken({
      providerAccountId: session.providerAccountId,
      providerLogin: session.providerLogin ?? null,
      email: session.user?.email ?? null,
    })
    target.searchParams.set("bridge_token", bridgeToken)
    return NextResponse.redirect(target)
  } catch (err) {
    console.error("Failed to sign bridge token", err)
    target.searchParams.set("error", "bridge_signing_failed")
    return NextResponse.redirect(target)
  }
}
