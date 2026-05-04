import { createFileRoute, isRedirect, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { isLoggedIn } from "@/hooks/useAuth"
import {
  type DashboardLandingPath,
  getDashboardLandingPath,
} from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/workshops")({
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_instructor && !user.is_superuser) {
        const target: DashboardLandingPath = getDashboardLandingPath(user)
        throw redirect({ to: target })
      }
    } catch (err) {
      if (isRedirect(err)) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: WorkshopsHub,
  head: () => ({
    meta: [{ title: "Workshops - Workshop" }],
  }),
})

function WorkshopsHub() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">Workshops hub</h1>
      <p className="text-muted-foreground text-sm">
        Lesson repos and session management will live here — placeholder for
        PR05+ slicing.
      </p>
    </div>
  )
}
