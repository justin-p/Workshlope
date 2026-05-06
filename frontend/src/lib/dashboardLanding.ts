import type { UserPublic } from "@/client"

export type DashboardLandingPath =
  | "/dashboard/instructor"
  | "/dashboard/trainee"
  | "/dashboard/admin"

/** Post-login landing per workshop plan (instructor beats superadmin default). */
export function getDashboardLandingPath(
  user: UserPublic,
): DashboardLandingPath {
  if (user.is_instructor) return "/dashboard/instructor"
  if (user.is_superuser) return "/dashboard/admin"
  return "/dashboard/trainee"
}

export function primaryHomeSidebarLabel(user: UserPublic): string {
  if (user.is_instructor) return "Instructor Home"
  if (user.is_superuser && !user.is_instructor) return "Admin Home"
  return "My Learning"
}
