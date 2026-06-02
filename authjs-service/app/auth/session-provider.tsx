"use client"

import { SessionProvider } from "next-auth/react"

export function AuthSessionProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const basePath =
    typeof window !== "undefined" &&
    window.location.pathname.startsWith("/auth-js/")
      ? "/auth-js/api/auth"
      : "/api/auth"

  return <SessionProvider basePath={basePath}>{children}</SessionProvider>
}
