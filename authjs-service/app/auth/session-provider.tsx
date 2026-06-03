"use client"

import { SessionProvider } from "next-auth/react"

export function AuthSessionProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const basePath = process.env.NEXT_PUBLIC_AUTHJS_API_BASE_PATH ?? "/api/auth"

  return <SessionProvider basePath={basePath}>{children}</SessionProvider>
}
