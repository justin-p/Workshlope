import { createFileRoute, isRedirect, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { isLoggedIn } from "@/hooks/useAuth"
import { getDashboardLandingPath } from "@/lib/dashboardLanding"

export const Route = createFileRoute("/_layout/")({
  beforeLoad: async () => {
    if (!isLoggedIn()) return
    try {
      const user = await UsersService.readUserMe()
      throw redirect({ to: getDashboardLandingPath(user) })
    } catch (err) {
      if (isRedirect(err)) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: LayoutIndexStub,
  head: () => ({
    meta: [{ title: "Workshop" }],
  }),
})

/** Never shown when logged in — `/` redirects to a role dashboard. */
function LayoutIndexStub() {
  return null
}
