import NextAuth, { type DefaultSession } from "next-auth"
import GitHub from "next-auth/providers/github"

declare module "next-auth" {
  interface Session {
    providerAccountId?: string | null
    providerLogin?: string | null
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  // Next strips basePath before route handlers see the request path, so keep
  // AUTH_URL at origin-only and force GitHub callback URI explicitly.
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
          redirect_uri: `${process.env.AUTH_URL}/auth-js/api/auth/callback/github`,
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
    // After successful GitHub sign-in we always route the browser through our
    // /api/bridge endpoint, which mints the bridge JWT and forwards it to the
    // FastAPI frontend's /auth/callback route.
    async redirect({ url, baseUrl }) {
      const target = new URL("/api/bridge", baseUrl)
      const callbackUrl =
        url.startsWith("http") || url.startsWith("/")
          ? url
          : `${baseUrl}${url}`
      target.searchParams.set("callbackUrl", callbackUrl)
      return target.toString()
    },
  },
})
