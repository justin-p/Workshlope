import { createFileRoute } from "@tanstack/react-router"

import { DashboardStubRails } from "@/components/dashboard/DashboardStubRails"
import { DashboardWorkshopSessions } from "@/components/dashboard/DashboardWorkshopSessions"

export const Route = createFileRoute("/_layout/dashboard/trainee")({
  component: TraineeDashboard,
  head: () => ({
    meta: [{ title: "My Learning - Workshop" }],
  }),
})

function TraineeDashboard() {
  return (
    <div data-testid="dashboard-home-root" className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">
        My Learning Home
      </h1>
      <p className="text-muted-foreground text-sm">
        Your sessions and progress (no peer roster on this dashboard).
      </p>
      <DashboardWorkshopSessions className="mt-6" />
      <DashboardStubRails persona="trainee" className="mt-6" />
    </div>
  )
}
