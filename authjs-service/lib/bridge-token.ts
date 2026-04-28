import { SignJWT } from "jose"

export interface BridgeIdentity {
  providerAccountId: string
  providerLogin?: string | null
  email?: string | null
}

const enc = new TextEncoder()

function requireEnv(name: string): string {
  const value = process.env[name]
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`)
  }
  return value
}

export async function signBridgeToken(
  identity: BridgeIdentity,
): Promise<string> {
  const secret = requireEnv("GITHUB_BRIDGE_SECRET")
  const audience = process.env.GITHUB_BRIDGE_AUDIENCE || "fastapi-bridge"
  const issuer = process.env.GITHUB_BRIDGE_ISSUER || "authjs"

  return await new SignJWT({
    provider: "github",
    provider_account_id: identity.providerAccountId,
    provider_login: identity.providerLogin ?? null,
    email: identity.email ?? null,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer(issuer)
    .setAudience(audience)
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(enc.encode(secret))
}
