import { createFileRoute, isRedirect, redirect } from "@tanstack/react-router"
import { UsersService } from "@/client"
import { DashboardStubRails } from "@/components/dashboard/DashboardStubRails"
import { DashboardWorkshopSessions } from "@/components/dashboard/DashboardWorkshopSessions"
import { isLoggedIn } from "@/hooks/useAuth"
import {
  type DashboardLandingPath,
  getDashboardLandingPath,
} from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/dashboard/instructor")({
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_instructor) {
        const target: DashboardLandingPath = getDashboardLandingPath(user)
        throw redirect({ to: target })
      }
    } catch (err) {
      if (isRedirect(err)) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: InstructorDashboard,
  head: () => ({
    meta: [{ title: "Instructor Home - Workshop" }],
  }),
})

function InstructorDashboard() {
  return (
    <div data-testid="dashboard-home-root" className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">Instructor Home</h1>
      <p className="text-muted-foreground text-sm">
        Sessions you lead and instructional tools ship here next.
      </p>
      <DashboardWorkshopSessions className="mt-6" workshopsHubLink />
      <DashboardStubRails persona="instructor" className="mt-6" />
    </div>
  )
}
