import { Award, BookOpen, Home, Trophy, Users } from "lucide-react"
import type { UserPublic } from "@/client"
import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import {
  getDashboardLandingPath,
  primaryHomeSidebarLabel,
} from "@/lib/dashboardLanding"
import { type Item, Main } from "./Main"
import { User } from "./User"

function buildNavItemsForUser(user: UserPublic): Item[] {
  const homePath = getDashboardLandingPath(user)
  const items: Item[] = [
    {
      icon: Home,
      title: primaryHomeSidebarLabel(user),
      path: homePath,
    },
    {
      icon: Trophy,
      title: "Badge leaderboard",
      path: "/workshop/badges/leaderboard",
    },
  ]
  if (user.is_instructor || user.is_superuser) {
    items.push({ icon: BookOpen, title: "Workshops", path: "/workshops" })
    items.push({ icon: Award, title: "Badges", path: "/workshop/badges" })
  }
  if (user.is_superuser) {
    items.push({ icon: Users, title: "Admin", path: "/admin" })
  }
  return items
}

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser ? buildNavItemsForUser(currentUser) : []

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
