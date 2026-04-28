import { NextResponse } from "next/server"

import { signBridgeToken } from "@/lib/bridge-token"

const FRONTEND_CALLBACK_URL =
  process.env.FRONTEND_CALLBACK_URL ?? "http://localhost:5173/auth/callback"

function hasBridgeConfig(): boolean {
  return Boolean(
    process.env.GITHUB_BRIDGE_SECRET &&
      process.env.GITHUB_BRIDGE_AUDIENCE &&
      process.env.GITHUB_BRIDGE_ISSUER,
  )
}

export async function GET() {
  const configReady = hasBridgeConfig()
  if (!configReady) {
    return NextResponse.json(
      {
        ok: false,
        service: "authjs-bridge",
        checks: {
          bridge_config: false,
          bridge_signing: false,
        },
      },
      { status: 503 },
    )
  }

  try {
    // Prove the service can sign bridge tokens with current config.
    await signBridgeToken({
      providerAccountId: "healthcheck",
      providerLogin: "healthcheck",
      email: "healthcheck@example.com",
    })

    return NextResponse.json({
      ok: true,
      service: "authjs-bridge",
      checks: {
        bridge_config: true,
        bridge_signing: true,
      },
      frontend_callback_url: FRONTEND_CALLBACK_URL,
    })
  } catch {
    return NextResponse.json(
      {
        ok: false,
        service: "authjs-bridge",
        checks: {
          bridge_config: true,
          bridge_signing: false,
        },
      },
      { status: 503 },
    )
  }
}
