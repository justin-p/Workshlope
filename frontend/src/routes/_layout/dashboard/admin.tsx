import { createFileRoute, isRedirect, redirect } from "@tanstack/react-router"
import { UsersService } from "@/client"
import { DashboardStubRails } from "@/components/dashboard/DashboardStubRails"
import { DashboardWorkshopSessions } from "@/components/dashboard/DashboardWorkshopSessions"
import { isLoggedIn } from "@/hooks/useAuth"
import {
  type DashboardLandingPath,
  getDashboardLandingPath,
} from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/dashboard/admin")({
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_superuser) {
        const target: DashboardLandingPath = getDashboardLandingPath(user)
        throw redirect({ to: target })
      }
    } catch (err) {
      if (isRedirect(err)) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: AdminDashboardHome,
  head: () => ({
    meta: [{ title: "Admin Home - Workshop" }],
  }),
})

function AdminDashboardHome() {
  return (
    <div data-testid="dashboard-home-root" className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">Admin Home</h1>
      <p className="text-muted-foreground text-sm">
        System overview and moderation entry points ship here next. Use sidebar
        <span className="font-medium text-foreground"> Admin </span>
        for user management tools today.
      </p>
      <DashboardWorkshopSessions
        className="mt-6"
        workshopsHubLink
        description="All workshop sessions in the system — open one to audit or join as superuser (seat required for controls)."
      />
      <DashboardStubRails persona="admin" className="mt-6" />
    </div>
  )
}
