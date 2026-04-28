import crypto from "node:crypto"

import { firstSuperuser, firstSuperuserPassword } from "../config"

function getEnvVar(name: string): string {
  const value = process.env[name]
  if (!value) {
    throw new Error(`Environment variable ${name} is undefined`)
  }
  return value
}

const bridgeSecret = getEnvVar("GITHUB_BRIDGE_SECRET")
const bridgeAudience = process.env.GITHUB_BRIDGE_AUDIENCE || "fastapi-bridge"
const bridgeIssuer = process.env.GITHUB_BRIDGE_ISSUER || "authjs"

const apiBase = process.env.VITE_API_URL || "http://localhost:8000"

interface BridgeTokenInput {
  providerAccountId: string
  providerLogin?: string
  email?: string
  fullName?: string
}

function base64UrlJson(obj: unknown): string {
  return Buffer.from(JSON.stringify(obj)).toString("base64url")
}

export function signBridgeToken(input: BridgeTokenInput): string {
  const header = { alg: "HS256", typ: "JWT" }
  const now = Math.floor(Date.now() / 1000)
  const payload: Record<string, unknown> = {
    iss: bridgeIssuer,
    aud: bridgeAudience,
    iat: now,
    exp: now + 5 * 60,
    provider: "github",
    provider_account_id: input.providerAccountId,
  }
  if (input.providerLogin) payload.provider_login = input.providerLogin
  if (input.email) payload.email = input.email
  if (input.fullName) payload.name = input.fullName

  const data = `${base64UrlJson(header)}.${base64UrlJson(payload)}`
  const signature = crypto
    .createHmac("sha256", bridgeSecret)
    .update(data)
    .digest("base64url")
  return `${data}.${signature}`
}

/**
 * Calls the bridge endpoint with a signed token to create or refresh a
 * pending GitHub login row. Returns the bridge response.
 */
export async function createPendingViaBridge(
  input: BridgeTokenInput,
): Promise<{
  status: "signed_in" | "pending_approval"
  pending_id: string | null
  access_token: string | null
}> {
  const bridgeToken = signBridgeToken(input)
  const res = await fetch(`${apiBase}/api/v1/oauth/github/bridge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bridge_token: bridgeToken }),
  })
  if (!res.ok) {
    throw new Error(
      `Bridge call failed (${res.status}): ${await res.text()}`,
    )
  }
  return await res.json()
}

/**
 * Login via the public access-token endpoint and return a bearer token
 * usable for direct API calls in tests.
 */
export async function getApiTokenAsSuperuser(): Promise<string> {
  const form = new URLSearchParams()
  form.set("username", firstSuperuser)
  form.set("password", firstSuperuserPassword)
  const res = await fetch(`${apiBase}/api/v1/login/access-token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  })
  if (!res.ok) {
    throw new Error(`Login failed (${res.status}): ${await res.text()}`)
  }
  const body = (await res.json()) as { access_token: string }
  return body.access_token
}

export async function deleteAllPending(): Promise<void> {
  const token = await getApiTokenAsSuperuser()
  const list = await fetch(
    `${apiBase}/api/v1/oauth/github/pending?limit=200`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  )
  if (!list.ok) return
  const body = (await list.json()) as {
    data: Array<{ id: string }>
  }
  await Promise.all(
    body.data.map((row) =>
      fetch(`${apiBase}/api/v1/oauth/github/pending/${row.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }),
    ),
  )
}
