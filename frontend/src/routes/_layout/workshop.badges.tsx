// Layout for /workshop/badges/* — requires login; child routes add instructor checks where needed.
import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/workshop/badges")({
  beforeLoad: async () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
  },
  component: WorkshopBadgesLayout,
})

function WorkshopBadgesLayout() {
  return <Outlet />
}
