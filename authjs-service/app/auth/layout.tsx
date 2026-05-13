import { AuthSessionProvider } from "./session-provider"

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <AuthSessionProvider>{children}</AuthSessionProvider>
}
