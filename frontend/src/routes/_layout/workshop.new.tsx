// Pre-create session wizard: lesson context, optional roster, then create session.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  isRedirect,
  Link,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { type ReactNode, useEffect, useState } from "react"
import { z } from "zod"

import {
  ApiError,
  UsersService,
  WorkshopLessonsService,
  WorkshopSessionsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useAuth from "@/hooks/useAuth"
import {
  type DashboardLandingPath,
  getDashboardLandingPath,
} from "@/lib/dashboardLanding"

const ROSTER_PICKER_LIMIT = 25
const ROSTER_PICKER_DEBOUNCE_MS = 350

const workshopNewSearchSchema = z.object({
  lessonId: z.string().uuid(),
  lessonTitle: z.string().optional(),
})

export const Route = createFileRoute("/_layout/workshop/new")({
  validateSearch: workshopNewSearchSchema,
  beforeLoad: async () => {
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
  component: WorkshopNewSessionWizard,
  head: () => ({
    meta: [{ title: "New workshop session - Workshop" }],
  }),
})

function WorkshopNewSessionWizard() {
  const { lessonId, lessonTitle } = Route.useSearch()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [rosterPickerSearch, setRosterPickerSearch] = useState("")
  const [debouncedRosterQ, setDebouncedRosterQ] = useState("")
  const [rosterPickerSkip, setRosterPickerSkip] = useState(0)
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedRosterQ(rosterPickerSearch.trim())
      setRosterPickerSkip(0)
    }, ROSTER_PICKER_DEBOUNCE_MS)
    return () => window.clearTimeout(t)
  }, [rosterPickerSearch])

  const prerequisitesQuery = useQuery({
    queryKey: ["workshopLessonPrerequisites", lessonId],
    queryFn: () => WorkshopLessonsService.readLessonPrerequisites({ lessonId }),
  })

  const rosterUserPickerQuery = useQuery({
    queryKey: [
      "workshopLessonRosterUserPicker",
      lessonId,
      debouncedRosterQ,
      rosterPickerSkip,
    ],
    queryFn: () =>
      WorkshopLessonsService.readLessonRosterUserPicker({
        lessonId,
        q: debouncedRosterQ.length >= 2 ? debouncedRosterQ : undefined,
        skip: rosterPickerSkip,
        limit: ROSTER_PICKER_LIMIT,
      }),
    enabled: step === 2,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      WorkshopSessionsService.createWorkshopSession({
        requestBody: {
          lesson_id: lessonId,
          participant_user_ids:
            selectedUserIds.size > 0 ? Array.from(selectedUserIds) : undefined,
        },
      }),
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({
        queryKey: ["workshopSessionsForUser"],
      })
      await navigate({
        to: "/workshop/$sessionId",
        params: { sessionId: data.session_id },
      })
    },
  })

  const displayTitle =
    lessonTitle?.trim() && lessonTitle.trim().length > 0
      ? lessonTitle.trim()
      : "Workshop lesson"

  const pickerNotice =
    rosterPickerSearch.trim().length > 0 && rosterPickerSearch.trim().length < 2
      ? "Enter at least 2 characters to search by name or email."
      : null

  const emptyRosterWarning =
    selectedUserIds.size === 0
      ? "You have not added any trainees to the roster yet. You can still create the session and add them later."
      : null

  return (
    <div className="space-y-6" data-testid="workshop-new-wizard">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Set up workshop session
          </h1>
          <p
            className="text-muted-foreground text-sm mt-1"
            data-testid="workshop-new-lesson-title"
          >
            Lesson: {displayTitle}
          </p>
        </div>
        <Button variant="outline" asChild data-testid="workshop-new-cancel">
          <Link to="/workshops">Cancel</Link>
        </Button>
      </div>

      <ol className="flex flex-wrap gap-4 text-sm text-muted-foreground border-b pb-3">
        <li className={step === 1 ? "text-foreground font-medium" : undefined}>
          1. Lesson and pre-work
        </li>
        <li className={step === 2 ? "text-foreground font-medium" : undefined}>
          2. Trainee roster
        </li>
        <li className={step === 3 ? "text-foreground font-medium" : undefined}>
          3. Review
        </li>
      </ol>

      {step === 1 ? (
        <section
          className="space-y-4 rounded-lg border p-4"
          data-testid="workshop-new-step-prereqs"
        >
          <h2 className="text-lg font-medium">Lesson and pre-work</h2>
          {prerequisitesQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">
              Loading prerequisites…
            </p>
          ) : prerequisitesQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Could not load prerequisites</AlertTitle>
              <AlertDescription>
                {prerequisitesQuery.error instanceof ApiError
                  ? ((
                      prerequisitesQuery.error.body as
                        | { detail?: string }
                        | undefined
                    )?.detail ?? prerequisitesQuery.error.message)
                  : "Request failed"}
              </AlertDescription>
            </Alert>
          ) : (prerequisitesQuery.data?.data ?? []).length === 0 ? (
            <p className="text-muted-foreground text-sm">
              This lesson has no prerequisites defined yet. Trainees will not
              see a pre-work checklist until prerequisites exist in the lesson
              manifest.
            </p>
          ) : (
            <ul className="list-disc pl-5 space-y-2 text-sm">
              {(prerequisitesQuery.data?.data ?? []).map((p) => (
                <li key={p.id}>
                  <span className="font-medium text-foreground">{p.title}</span>
                  {p.required_flag ? (
                    <Badge className="ml-2" variant="secondary">
                      Required
                    </Badge>
                  ) : (
                    <Badge className="ml-2" variant="outline">
                      Optional
                    </Badge>
                  )}
                  {p.url ? (
                    <span className="block text-muted-foreground text-xs mt-0.5">
                      Link: {p.url}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" onClick={() => setStep(2)}>
              Next: Trainee roster
            </Button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section
          className="space-y-4 rounded-lg border p-4"
          data-testid="workshop-new-step-roster"
        >
          <h2 className="text-lg font-medium">Trainee roster</h2>
          <p className="text-muted-foreground text-sm">
            Select users to add to the roster when the session is created. You
            can skip this step and add trainees later from the session page.
          </p>
          <div className="space-y-2">
            <label
              htmlFor="workshop-new-roster-search"
              className="text-xs text-muted-foreground"
            >
              Find users
              <div className="mt-1 flex flex-wrap items-end gap-2">
                <Input
                  id="workshop-new-roster-search"
                  type="text"
                  value={rosterPickerSearch}
                  onChange={(e) => setRosterPickerSearch(e.target.value)}
                  data-testid="workshop-new-roster-user-picker-search"
                  placeholder="Search by full name or email"
                  className="w-[min(360px,100%)]"
                />
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2"
                    data-testid="workshop-new-roster-user-picker-page-prev"
                    disabled={rosterPickerSkip <= 0}
                    onClick={() =>
                      setRosterPickerSkip((s) =>
                        Math.max(0, s - ROSTER_PICKER_LIMIT),
                      )
                    }
                  >
                    Prev
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2"
                    data-testid="workshop-new-roster-user-picker-page-next"
                    disabled={
                      (rosterUserPickerQuery.data?.count ?? 0) <=
                      rosterPickerSkip + ROSTER_PICKER_LIMIT
                    }
                    onClick={() =>
                      setRosterPickerSkip((s) => s + ROSTER_PICKER_LIMIT)
                    }
                  >
                    Next
                  </Button>
                </div>
              </div>
            </label>
            {pickerNotice ? (
              <p
                className="text-xs text-muted-foreground"
                data-testid="workshop-new-roster-picker-notice"
              >
                {pickerNotice}
              </p>
            ) : null}
            {rosterUserPickerQuery.isError ? (
              <Alert variant="destructive">
                <AlertTitle>Could not load users</AlertTitle>
                <AlertDescription>
                  {rosterUserPickerQuery.error instanceof ApiError
                    ? ((
                        rosterUserPickerQuery.error.body as
                          | { detail?: string }
                          | undefined
                      )?.detail ?? rosterUserPickerQuery.error.message)
                    : rosterUserPickerQuery.error instanceof Error
                      ? rosterUserPickerQuery.error.message
                      : "Request failed"}
                </AlertDescription>
              </Alert>
            ) : null}
            {rosterUserPickerQuery.isLoading ? (
              <p className="text-xs text-muted-foreground">Loading users…</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[44px]" scope="col">
                      <span className="sr-only">Select</span>
                    </TableHead>
                    <TableHead className="w-[120px]" scope="col">
                      Type
                    </TableHead>
                    <TableHead scope="col">Email</TableHead>
                    <TableHead scope="col">Full name</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody data-testid="workshop-new-roster-user-picker-table">
                  {(rosterUserPickerQuery.data?.data ?? []).length ? (
                    (rosterUserPickerQuery.data?.data ?? []).map((row) => {
                      const isSelf = currentUser?.id === row.user_id
                      const disabled = isSelf || !row.is_active
                      const selected = selectedUserIds.has(row.user_id)
                      const typeBadges: ReactNode[] = []
                      if (row.is_superuser) {
                        typeBadges.push(
                          <Badge key="superuser" variant="secondary">
                            Superuser
                          </Badge>,
                        )
                      }
                      if (row.is_instructor) {
                        typeBadges.push(
                          <Badge key="instructor" variant="outline">
                            Instructor
                          </Badge>,
                        )
                      }
                      if (typeBadges.length === 0) {
                        typeBadges.push(
                          <Badge key="trainee" variant="outline">
                            Trainee
                          </Badge>,
                        )
                      }
                      return (
                        <TableRow key={row.user_id}>
                          <TableCell>
                            <Checkbox
                              checked={selected}
                              disabled={disabled}
                              aria-label={`Select ${row.email}`}
                              onCheckedChange={(checked) => {
                                if (typeof checked !== "boolean") return
                                setSelectedUserIds((prev) => {
                                  const next = new Set(prev)
                                  if (checked) next.add(row.user_id)
                                  else next.delete(row.user_id)
                                  return next
                                })
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {typeBadges}
                              {!row.is_active ? (
                                <Badge
                                  variant="destructive"
                                  className="opacity-80"
                                  title="Account inactive"
                                >
                                  Inactive
                                </Badge>
                              ) : null}
                              {isSelf ? (
                                <Badge
                                  variant="outline"
                                  title="You are the lead instructor"
                                >
                                  You
                                </Badge>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell className="max-w-[240px] truncate">
                            {row.email}
                          </TableCell>
                          <TableCell>{row.full_name ?? "—"}</TableCell>
                        </TableRow>
                      )
                    })
                  ) : (
                    <TableRow>
                      <TableCell colSpan={4} className="text-center text-sm">
                        No users match this page.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            )}
          </div>
          <div className="flex flex-wrap justify-between gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button type="button" onClick={() => setStep(3)}>
              Next: Review
            </Button>
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section
          className="space-y-4 rounded-lg border p-4"
          data-testid="workshop-new-step-confirm"
        >
          <h2 className="text-lg font-medium">Review and create</h2>
          <p className="text-sm text-muted-foreground">
            Creating the session will take you to the instructor workshop page
            for scheduling, roster changes, and starting the session.
          </p>
          {emptyRosterWarning ? (
            <Alert data-testid="workshop-new-empty-roster-warning">
              <AlertTitle>Empty roster</AlertTitle>
              <AlertDescription>{emptyRosterWarning}</AlertDescription>
            </Alert>
          ) : null}
          <p className="text-sm">
            <span className="font-medium">Trainees selected:</span>{" "}
            {selectedUserIds.size}
          </p>
          <div className="flex flex-wrap justify-between gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => setStep(2)}>
              Back
            </Button>
            <Button
              type="button"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
              data-testid="workshop-new-confirm-create"
            >
              {createMutation.isPending ? "Creating…" : "Create session"}
            </Button>
          </div>
          {createMutation.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Could not create session</AlertTitle>
              <AlertDescription>
                {createMutation.error instanceof ApiError
                  ? ((
                      createMutation.error.body as
                        | { detail?: string }
                        | undefined
                    )?.detail ?? createMutation.error.message)
                  : createMutation.error instanceof Error
                    ? createMutation.error.message
                    : "Request failed"}
              </AlertDescription>
            </Alert>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
