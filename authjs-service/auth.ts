import NextAuth, { type DefaultSession } from "next-auth"
import GitHub from "next-auth/providers/github"

function normalizeAuthApiBasePath(raw: string | undefined): string {
  const trimmed = (raw ?? "").trim()
  if (!trimmed) return "/api/auth"
  const withLeading = trimmed.startsWith("/") ? trimmed : `/${trimmed}`
  return withLeading.replace(/\/+$/, "") || "/api/auth"
}

const authApiBasePath = normalizeAuthApiBasePath(
  process.env.NEXT_PUBLIC_AUTHJS_API_BASE_PATH,
)
const bridgePath = authApiBasePath.endsWith("/api/auth")
  ? `${authApiBasePath.slice(0, -"/api/auth".length)}/api/bridge` || "/api/bridge"
  : "/api/bridge"

declare module "next-auth" {
  interface Session {
    providerAccountId?: string | null
    providerLogin?: string | null
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  // Parse actions from /api/auth/* while app is exposed under /auth-js/*.
  basePath: "/api/auth",
  // Built-in Preact sign-in page uses fixed grays; use our Next page instead.
  pages: {
    signIn: "/auth/signin",
  },
  // Still applied to built-in error / verify-request HTML if those render.
  theme: {
    colorScheme: "dark",
    brandColor: "#14b8a6",
  },
  providers: [
    GitHub({
      clientId: process.env.GITHUB_CLIENT_ID,
      clientSecret: process.env.GITHUB_CLIENT_SECRET,
      authorization: {
        params: {
          redirect_uri: `${process.env.AUTH_URL}${authApiBasePath}/callback/github`,
        },
      },
      profile(profile) {
        return {
          id: String(profile.id),
          name: profile.name ?? profile.login ?? null,
          email: profile.email ?? null,
          image: profile.avatar_url ?? null,
          // Custom fields surfaced through the JWT callback below.
          login: profile.login,
          providerAccountId: String(profile.id),
        } as DefaultSession["user"] & {
          login: string
          providerAccountId: string
        }
      },
    }),
  ],
  callbacks: {
    async jwt({ token, profile, account, user }) {
      const mutableToken = token as {
        email?: string | null
        providerAccountId?: string | null
        providerLogin?: string | null
      }
      if (account?.provider === "github" && profile) {
        const ghProfile = profile as {
          id: number | string
          login?: string
          email?: string | null
        }
        mutableToken.providerAccountId = String(ghProfile.id)
        mutableToken.providerLogin = ghProfile.login ?? null
        if (!mutableToken.email && ghProfile.email) mutableToken.email = ghProfile.email
      }
      if (user && (user as { providerAccountId?: string }).providerAccountId) {
        mutableToken.providerAccountId = (
          user as { providerAccountId: string }
        ).providerAccountId
      }
      return mutableToken
    },
    async session({ session, token }) {
      const sessionToken = token as {
        providerAccountId?: string | null
        providerLogin?: string | null
      }
      session.providerAccountId = sessionToken.providerAccountId ?? null
      session.providerLogin = sessionToken.providerLogin ?? null
      return session
    },
    // After successful GitHub sign-in we route the browser through our
    // dynamic /api/bridge endpoint (path-mounted in prod), which mints the bridge
    // JWT and forwards it
    // to the frontend /auth/callback route.
    async redirect({ url, baseUrl }) {
      const normalized =
        url.startsWith("http") || url.startsWith("/")
          ? new URL(url, baseUrl)
          : new URL(`${baseUrl}${url}`)

      // Avoid recursively wrapping an already-bridged URL.
      if (normalized.pathname === bridgePath) {
        return normalized.toString()
      }

      const target = new URL(bridgePath, baseUrl)
      target.searchParams.set("callbackUrl", normalized.toString())
      return target.toString()
    },
  },
})
