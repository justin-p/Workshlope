import { Link } from "@tanstack/react-router"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

type Persona = "trainee" | "instructor" | "admin"

type StubCard = {
  title: string
  description: string
  /** In-app shortcut when the route exists today */
  linkTo?: string
  linkLabel?: string
}

const RAILS: Record<Persona, StubCard[]> = {
  trainee: [
    {
      title: "Your sessions",
      description:
        "Soon: live and starting-soon tiles for workshops where you have a seat — scoped to you only (no peer roster here).",
    },
    {
      title: "Continue learning",
      description:
        "Soon: deep links back into the lesson part you last opened per session.",
    },
    {
      title: "Badges & progress",
      description:
        "Soon: earned badges and personal completion trends (no cohort or peer metrics).",
    },
    {
      title: "Account",
      description: "Profile, email, and password live under Settings.",
      linkTo: "/settings",
      linkLabel: "Open settings",
    },
  ],
  instructor: [
    {
      title: "Live & paused rooms",
      description:
        "Soon: at-a-glance tiles for sessions you lead that are active or paused.",
      linkTo: "/workshops",
      linkLabel: "Workshops hub",
    },
    {
      title: "Starting today",
      description:
        "Soon: scheduled starts and reminder context for your sessions.",
    },
    {
      title: "Completion reviews",
      description: "Soon: pending verification queue before badges are issued.",
    },
    {
      title: "Lesson source health",
      description:
        "Soon: unhealthy repos and sync failures surfaced with clear next steps.",
    },
  ],
  admin: [
    {
      title: "User management",
      description:
        "Create, edit, and deactivate accounts via the legacy admin table UI.",
      linkTo: "/admin",
      linkLabel: "Open admin",
    },
    {
      title: "Moderation overview",
      description:
        "Soon: OAuth pending approvals rollup and instructor roster signals.",
    },
    {
      title: "Operational health",
      description:
        "Soon: aggregated warnings (sync failures, unhealthy lesson sources).",
    },
  ],
}

export function DashboardStubRails({
  persona,
  className,
}: {
  persona: Persona
  className?: string
}) {
  const stubs = RAILS[persona]

  return (
    <div
      data-testid={`dashboard-stub-rail-${persona}`}
      className={cn("grid gap-4 sm:grid-cols-2", className)}
    >
      {stubs.map((s) => (
        <Card key={s.title}>
          <CardHeader>
            <CardTitle className="text-base">{s.title}</CardTitle>
            <CardDescription>{s.description}</CardDescription>
          </CardHeader>
          {s.linkTo ? (
            <CardContent className="pt-0">
              <Link
                to={s.linkTo}
                className="text-primary text-sm font-medium underline underline-offset-4"
              >
                {s.linkLabel ?? s.linkTo}
              </Link>
            </CardContent>
          ) : null}
        </Card>
      ))}
    </div>
  )
}
