import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
}

interface MainProps {
  items: Item[]
}

function navItemMatchesPath(currentPath: string, itemPath: string): boolean {
  if (currentPath === itemPath) return true
  if (itemPath.length <= 1) return false
  return currentPath.startsWith(`${itemPath}/`)
}

/** When two items share a prefix (e.g. /workshop/badges vs /workshop/badges/leaderboard), only the longest matching path is active. */
function activeNavPathForItems(
  currentPath: string,
  navItems: Item[],
): string | null {
  const matches = navItems.filter((item) =>
    navItemMatchesPath(currentPath, item.path),
  )
  if (matches.length === 0) return null
  return matches.reduce((best, item) =>
    item.path.length > best.path.length ? item : best,
  ).path
}

export function Main({ items }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname
  const activeNavPath = activeNavPathForItems(currentPath, items)

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const isActive = activeNavPath === item.path

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  <RouterLink to={item.path} onClick={handleMenuClick}>
                    <item.icon />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
