import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"

import { ApiError, WorkshopLessonReposService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const RECENT_REPOS_KEY = "workshop.lessonRepoSync.recentRepos"
const INSTALLATION_PREF_KEY = "workshop.lessonRepoSync.lastInstallationId"

type InstallationRowLite = {
  installation_id: number
  account_login: string
}

function sortInstallationRows(
  rows: InstallationRowLite[],
): InstallationRowLite[] {
  return [...rows].sort(
    (a, b) =>
      a.account_login.localeCompare(b.account_login) ||
      a.installation_id - b.installation_id,
  )
}

function persistInstallationPreference(installationId: number) {
  try {
    localStorage.setItem(INSTALLATION_PREF_KEY, String(installationId))
  } catch {
    // Ignore localStorage write failures in private/locked contexts.
  }
}

function pickInstallationIdFromRows(rows: InstallationRowLite[]): number {
  if (rows.length === 1) {
    return rows[0].installation_id
  }
  try {
    const raw = localStorage.getItem(INSTALLATION_PREF_KEY)
    const saved = raw ? Number.parseInt(raw, 10) : NaN
    if (
      Number.isFinite(saved) &&
      saved > 0 &&
      rows.some((r) => r.installation_id === saved)
    ) {
      return saved
    }
  } catch {
    // Ignore localStorage read failures.
  }
  return sortInstallationRows(rows)[0].installation_id
}
const OWNER_REPO_RE = /^[^/\s]+\/[^/\s]+$/
const COPY_ID_FEEDBACK_MS = 1500
const FRESH_AGE_MS = 60_000
const AGING_AGE_MS = 5 * 60_000
type RepoHealthFilter = "all" | "healthy" | "unhealthy"

type LessonRepoPreviewPart = {
  slug: string
  title: string
  ordering: number
  path: string
}

type LessonRepoPreviewLesson = {
  lesson_id: string
  lesson_slug: string
  lesson_title: string
  parts: LessonRepoPreviewPart[]
}

type LessonRepoPreview = {
  lesson_repo_id: string
  full_name: string
  default_branch: string
  health: string
  lessons: LessonRepoPreviewLesson[]
}

function formatSyncTimestamp(iso: string | null | undefined): string {
  if (!iso) return "never synced"
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return "unknown sync time"
  return dt.toLocaleString()
}

function buildRecentRepos(nextRepo: string, recentRepos: string[]): string[] {
  return [nextRepo, ...recentRepos.filter((r) => r !== nextRepo)].slice(0, 5)
}

export function WorkshopLessonRepoSyncCard() {
  const queryClient = useQueryClient()
  const repoOwnerNameDatalistId = useId()
  const lastAutofillFingerprintForEmpty = useRef<string | null>(null)
  const [fullName, setFullName] = useState("")
  const [installationId, setInstallationId] = useState("")
  const [recentRepos, setRecentRepos] = useState<string[]>([])
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [copiedInstallationId, setCopiedInstallationId] = useState<
    number | null
  >(null)
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null)
  const [previewByRepoId, setPreviewByRepoId] = useState<
    Record<string, LessonRepoPreview | undefined>
  >({})
  const [expandedPreviewRepoIds, setExpandedPreviewRepoIds] = useState<
    Record<string, boolean>
  >({})
  const [previewLoadingRepoId, setPreviewLoadingRepoId] = useState<
    string | null
  >(null)
  const [previewErrorByRepoId, setPreviewErrorByRepoId] = useState<
    Record<string, string | undefined>
  >({})
  const [healthFilter, setHealthFilter] = useState<RepoHealthFilter>("all")
  const [repoSearch, setRepoSearch] = useState("")
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [advancedManualOpen, setAdvancedManualOpen] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    try {
      const raw = localStorage.getItem(RECENT_REPOS_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as unknown
      if (!Array.isArray(parsed)) return
      const repos = parsed
        .filter((v): v is string => typeof v === "string")
        .slice(0, 5)
      setRecentRepos(repos)
    } catch {
      setRecentRepos([])
    }
  }, [])

  const syncMutation = useMutation({
    mutationFn: (payload: { full_name: string; installation_id: number }) =>
      WorkshopLessonReposService.syncLessonRepoFromGithub({
        requestBody: payload,
      }),
    onSuccess: async () => {
      setErrorDetail(null)
      const normalized = fullName.trim()
      if (OWNER_REPO_RE.test(normalized)) {
        const next = buildRecentRepos(normalized, recentRepos)
        setRecentRepos(next)
        try {
          localStorage.setItem(RECENT_REPOS_KEY, JSON.stringify(next))
        } catch {
          // Ignore localStorage write failures in private/locked contexts.
        }
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workshopLessonRepos"] }),
        queryClient.invalidateQueries({
          queryKey: ["workshopGithubInstallations"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["workshopInstallationAccessibleRepos"],
        }),
      ])
      setLastRefreshedAt(new Date())
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) {
        const body = e.body as { detail?: string } | undefined
        setErrorDetail(body?.detail ?? e.message)
        return
      }
      setErrorDetail(e instanceof Error ? e.message : "Sync request failed")
    },
  })

  const goToSessionSetupWizard = useCallback(
    (lesson: LessonRepoPreviewLesson) => {
      void navigate({
        to: "/workshop/new",
        search: {
          lessonId: lesson.lesson_id,
          lessonTitle: lesson.lesson_title,
        },
      })
    },
    [navigate],
  )
  const normalizedRepo = fullName.trim()
  const repoFormatValid =
    normalizedRepo.length === 0 || OWNER_REPO_RE.test(normalizedRepo)
  const installationIdInt = Number.parseInt(installationId, 10)
  const installationIdValid =
    installationId.length === 0 ||
    (Number.isFinite(installationIdInt) && installationIdInt > 0)
  const showRepoValidation = normalizedRepo.length > 0 && !repoFormatValid
  const showInstallationValidation =
    installationId.length > 0 && !installationIdValid

  const reposQuery = useQuery({
    queryKey: [
      "workshopLessonRepos",
      installationIdInt,
      healthFilter,
      repoSearch,
    ],
    queryFn: () =>
      WorkshopLessonReposService.readLessonRepos({
        skip: 0,
        limit: 20,
        installationId:
          Number.isFinite(installationIdInt) && installationIdInt > 0
            ? installationIdInt
            : undefined,
        health: healthFilter,
        q: repoSearch.trim() || undefined,
      }),
  })
  const installationsQuery = useQuery({
    queryKey: ["workshopGithubInstallations"],
    queryFn: () =>
      WorkshopLessonReposService.readGithubInstallations({
        skip: 0,
        limit: 50,
      }),
  })
  useEffect(() => {
    const rawRows = installationsQuery.data?.data ?? []
    const rows: InstallationRowLite[] = rawRows.map((r) => ({
      installation_id: r.installation_id,
      account_login: r.account_login,
    }))
    if (!installationsQuery.isSuccess || rows.length === 0) {
      return
    }

    const fingerprint = rows
      .map((r) => r.installation_id)
      .sort((a, b) => a - b)
      .join(",")

    const currentTrim = installationId.trim()
    if (currentTrim !== "") {
      const parsed = Number.parseInt(currentTrim, 10)
      if (
        Number.isFinite(parsed) &&
        parsed > 0 &&
        rows.some((r) => r.installation_id === parsed)
      ) {
        persistInstallationPreference(parsed)
        lastAutofillFingerprintForEmpty.current = fingerprint
        return
      }
      // GitHub no longer returns this installation (e.g. app was uninstalled).
      lastAutofillFingerprintForEmpty.current = null
      setInstallationId("")
      setFullName("")
      setErrorDetail(null)
      return
    }

    if (lastAutofillFingerprintForEmpty.current === fingerprint) {
      return
    }
    lastAutofillFingerprintForEmpty.current = fingerprint

    const pick = pickInstallationIdFromRows(rows)
    setInstallationId(String(pick))
    persistInstallationPreference(pick)
  }, [
    installationId,
    installationsQuery.isSuccess,
    installationsQuery.data?.data,
  ])

  const installCtaHref = installationsQuery.data?.install_url ?? null
  const hasInstallKickoff = Boolean(installCtaHref)
  const installationsCount = installationsQuery.data?.count ?? 0
  const hasAnyInstallations = installationsCount > 0
  const selectedInstallation = useMemo(() => {
    if (!Number.isFinite(installationIdInt)) return null
    return (
      installationsQuery.data?.data.find(
        (inst) => inst.installation_id === installationIdInt,
      ) ?? null
    )
  }, [installationIdInt, installationsQuery.data?.data])

  const sortedInstallRows = useMemo(() => {
    const raw = installationsQuery.data?.data ?? []
    return [...raw].sort(
      (a, b) =>
        a.account_login.localeCompare(b.account_login) ||
        a.installation_id - b.installation_id,
    )
  }, [installationsQuery.data?.data])

  /** Installation + repo pickers when we have cached installs from the API */
  const primaryPickerMode =
    installationsQuery.isSuccess && sortedInstallRows.length > 0
  /** Empty install list — allow typing IDs until GitHub/sync populates rows */
  const showManualFallback = installationsQuery.isSuccess && !primaryPickerMode

  const accessibleReposQuery = useQuery({
    queryKey: ["workshopInstallationAccessibleRepos", installationIdInt],
    queryFn: () =>
      WorkshopLessonReposService.readGithubInstallationAccessibleRepositories({
        installationId: installationIdInt,
      }),
    enabled:
      installationsQuery.isSuccess &&
      hasAnyInstallations &&
      Number.isFinite(installationIdInt) &&
      installationIdInt > 0,
  })

  /** Prefer live GitHub list; fall back to DB entitlements while loading/on error ("selected" installs). */
  const repoNameSuggestions = useMemo(() => {
    if (accessibleReposQuery.isSuccess) {
      return accessibleReposQuery.data.full_names
    }
    const entitled = selectedInstallation?.entitled_repositories ?? []
    if (
      selectedInstallation?.repository_selection === "selected" &&
      entitled.length > 0
    ) {
      return entitled
    }
    return []
  }, [
    accessibleReposQuery.data?.full_names,
    accessibleReposQuery.isSuccess,
    selectedInstallation?.repository_selection,
    selectedInstallation?.entitled_repositories,
  ])

  const dedupedRepoNameSuggestions = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const name of repoNameSuggestions) {
      if (seen.has(name)) continue
      seen.add(name)
      out.push(name)
    }
    return out
  }, [repoNameSuggestions])

  const installationSelectValue =
    primaryPickerMode &&
    sortedInstallRows.some((row) => row.installation_id === installationIdInt)
      ? String(installationIdInt)
      : undefined

  const selectedInstallLiveListsNoRepos =
    selectedInstallation?.repository_selection === "selected" &&
    accessibleReposQuery.isSuccess &&
    (accessibleReposQuery.data?.full_names?.length ?? 0) === 0

  /** DB mirror may lag after install — only nag when GitHub confirms no repo access too. */
  const selectedInstallationNeedsGrant =
    selectedInstallation?.repository_selection === "selected" &&
    (selectedInstallation.entitled_repositories?.length ?? 0) === 0 &&
    selectedInstallLiveListsNoRepos
  const blockingSetupHint = !installationsQuery.isSuccess
    ? null
    : !hasAnyInstallations
      ? hasInstallKickoff
        ? "No installations loaded yet — use Discover / Refresh lists, or install the GitHub App from the link below."
        : "GitHub App setup is not configured yet. Ask a platform admin to set GITHUB_APP_SLUG or GITHUB_APP_INSTALL_URL."
      : selectedInstallationNeedsGrant
        ? "Grant repository access for the selected installation before syncing."
        : null

  const canSubmit =
    normalizedRepo.length > 0 &&
    repoFormatValid &&
    installationIdValid &&
    Number.isFinite(installationIdInt) &&
    blockingSetupHint === null &&
    !syncMutation.isPending

  const visibleSyncedRepos = useMemo(
    () => reposQuery.data?.data ?? [],
    [reposQuery.data?.data],
  )

  const isRefreshingData =
    reposQuery.isFetching || installationsQuery.isFetching
  const isBusy = syncMutation.isPending || isRefreshingData
  const freshnessLabel = useMemo(() => {
    if (!lastRefreshedAt) return "not refreshed yet"
    const ageMs = Date.now() - lastRefreshedAt.getTime()
    if (ageMs < FRESH_AGE_MS) return "fresh"
    if (ageMs < AGING_AGE_MS) return "aging"
    return "stale"
  }, [lastRefreshedAt])
  const statusMessage = useMemo(() => {
    if (syncMutation.isPending) return "Sync in progress..."
    if (isRefreshingData)
      return "Refreshing installation and repository lists..."
    if (blockingSetupHint) return blockingSetupHint
    if (syncMutation.data) {
      return `Last sync succeeded for ${syncMutation.data.full_name}.`
    }
    return primaryPickerMode
      ? "Choose an installation and repository, then sync."
      : "Ready to sync from GitHub."
  }, [
    blockingSetupHint,
    isRefreshingData,
    primaryPickerMode,
    syncMutation.data,
    syncMutation.isPending,
  ])

  useEffect(() => {
    if (
      !lastRefreshedAt &&
      reposQuery.isSuccess &&
      installationsQuery.isSuccess
    ) {
      setLastRefreshedAt(new Date())
    }
  }, [installationsQuery.isSuccess, lastRefreshedAt, reposQuery.isSuccess])

  const onSubmit = () => {
    if (!canSubmit) return
    syncMutation.mutate({
      full_name: fullName.trim(),
      installation_id: installationIdInt,
    })
  }

  const copyInstallationId = async (value: number) => {
    try {
      await navigator.clipboard.writeText(String(value))
      setCopiedInstallationId(value)
      setTimeout(() => {
        setCopiedInstallationId((current) =>
          current === value ? null : current,
        )
      }, COPY_ID_FEEDBACK_MS)
    } catch {
      // Ignore clipboard write failures silently.
    }
  }

  const refreshCardData = useCallback(async () => {
    const apiBase = (import.meta.env.VITE_API_URL as string | undefined)?.trim()
    const baseUrl =
      apiBase && apiBase.length > 0 ? apiBase : window.location.origin
    const token = localStorage.getItem("access_token")
    const authHeaders = new Headers()
    if (token) {
      authHeaders.set("Authorization", `Bearer ${token}`)
    }
    setRefreshError(null)
    try {
      const installRefreshResponse = await fetch(
        `${baseUrl}/api/v1/workshop/lesson-repos/installations/refresh`,
        {
          method: "POST",
          headers: new Headers({
            "content-type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          }),
          body: JSON.stringify({ include_repositories: false }),
        },
      )
      if (!installRefreshResponse.ok) {
        const body = (await installRefreshResponse.json()) as
          | { detail?: string }
          | undefined
        throw new Error(body?.detail ?? "Failed to refresh installations")
      }
      if (Number.isFinite(installationIdInt) && installationIdInt > 0) {
        const entitlementResponse = await fetch(
          `${baseUrl}/api/v1/workshop/lesson-repos/installations/${installationIdInt}/repositories/refresh`,
          {
            method: "POST",
            headers: authHeaders,
          },
        )
        if (!entitlementResponse.ok) {
          const body = (await entitlementResponse.json()) as
            | { detail?: string }
            | undefined
          throw new Error(
            body?.detail ?? "Failed to refresh installation repositories",
          )
        }
      }
    } catch (error) {
      setRefreshError(
        error instanceof Error
          ? error.message
          : "Failed to refresh installation metadata",
      )
    }
    await Promise.all([reposQuery.refetch(), installationsQuery.refetch()])
    void queryClient.invalidateQueries({
      queryKey: ["workshopInstallationAccessibleRepos"],
    })
    setLastRefreshedAt(new Date())
  }, [
    installationIdInt,
    installationsQuery.refetch,
    queryClient,
    reposQuery.refetch,
  ])

  const clearInputs = () => {
    setFullName("")
    lastAutofillFingerprintForEmpty.current = null
    setInstallationId("")
    setErrorDetail(null)
    setRefreshError(null)
    setAdvancedManualOpen(false)
  }

  const loadRepoPreview = async (
    repoId: string,
  ): Promise<LessonRepoPreview | undefined> => {
    const apiBase = (import.meta.env.VITE_API_URL as string | undefined)?.trim()
    const baseUrl =
      apiBase && apiBase.length > 0 ? apiBase : window.location.origin
    const token = localStorage.getItem("access_token")
    setPreviewLoadingRepoId(repoId)
    setPreviewErrorByRepoId((prev) => ({ ...prev, [repoId]: undefined }))
    try {
      const response = await fetch(
        `${baseUrl}/api/v1/workshop/lesson-repos/${repoId}/preview`,
        {
          method: "GET",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        },
      )
      const body = (await response.json()) as
        | LessonRepoPreview
        | { detail?: string }
      if (!response.ok) {
        const detail =
          typeof body === "object" && body && "detail" in body
            ? (body.detail ?? "Could not load preview")
            : "Could not load preview"
        setPreviewErrorByRepoId((prev) => ({ ...prev, [repoId]: detail }))
        return undefined
      }
      const preview = body as LessonRepoPreview
      setPreviewByRepoId((prev) => ({
        ...prev,
        [repoId]: preview,
      }))
      setExpandedPreviewRepoIds((prev) => ({ ...prev, [repoId]: true }))
      return preview
    } catch {
      setPreviewErrorByRepoId((prev) => ({
        ...prev,
        [repoId]: "Could not load preview",
      }))
      return undefined
    } finally {
      setPreviewLoadingRepoId((current) =>
        current === repoId ? null : current,
      )
    }
  }

  const toggleRepoPreview = async (repoId: string) => {
    if (expandedPreviewRepoIds[repoId]) {
      setExpandedPreviewRepoIds((prev) => ({ ...prev, [repoId]: false }))
      return
    }
    if (previewByRepoId[repoId]) {
      setExpandedPreviewRepoIds((prev) => ({ ...prev, [repoId]: true }))
      return
    }
    await loadRepoPreview(repoId)
  }

  const handleUseLessonFromRepo = async (repoId: string) => {
    const cached = previewByRepoId[repoId]
    const preview = cached ?? (await loadRepoPreview(repoId))
    if (!preview) return
    if (preview.lessons.length === 1) {
      goToSessionSetupWizard(preview.lessons[0])
      return
    }
    setExpandedPreviewRepoIds((prev) => ({ ...prev, [repoId]: true }))
  }

  return (
    <Card data-testid="workshop-lesson-repo-sync-card">
      <CardHeader>
        <CardTitle className="text-base">Lesson GitHub sync</CardTitle>
        <CardDescription>
          Install/configure the GitHub App, then sync lesson markdown from a
          repo into workshop lessons.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Need to install or adjust repository access first?{" "}
          {installCtaHref ? (
            <>
              Open{" "}
              <a
                href={installCtaHref}
                target="_blank"
                rel="noreferrer noopener"
                className="underline text-primary"
              >
                GitHub App installations
              </a>
              .
            </>
          ) : (
            <>
              First create and configure the GitHub App, then return here to
              install and grant repo access.
            </>
          )}
        </p>
        {installationsQuery.isSuccess && !hasAnyInstallations ? (
          <div
            className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200"
            data-testid="workshop-sync-install-prompt"
          >
            <p className="font-medium">No installations in app state yet</p>
            {installCtaHref ? (
              <>
                <p className="mt-1">
                  Listing installations syncs metadata from GitHub on each load.
                  If you still see none, check backend GitHub App credentials or
                  use{" "}
                  <strong className="font-medium">
                    Discover / Refresh lists
                  </strong>{" "}
                  below to retry and refresh repository grant rows.
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    disabled={isBusy}
                    onClick={() => void refreshCardData()}
                    data-testid="workshop-sync-discover-installations"
                  >
                    Discover installations now
                  </Button>
                  <a
                    href={installCtaHref}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex h-7 items-center rounded-md border border-input bg-transparent px-2 text-xs underline text-primary hover:bg-accent"
                  >
                    Open GitHub to install/configure
                  </a>
                </div>
              </>
            ) : (
              <>
                <p>
                  No install kickoff URL is configured. Platform admins should
                  set <code>GITHUB_APP_SLUG</code> or{" "}
                  <code>GITHUB_APP_INSTALL_URL</code> in backend env.
                </p>
                <a
                  href="https://docs.github.com/en/apps/creating-github-apps"
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline text-primary"
                >
                  Create a GitHub App
                </a>
              </>
            )}
          </div>
        ) : null}
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {statusMessage}
        </p>
        {installationsQuery.isError ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs">
            <span className="text-destructive">
              Could not load installations.
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => void installationsQuery.refetch()}
              disabled={isBusy}
            >
              Retry
            </Button>
          </div>
        ) : null}

        {!installationsQuery.isSuccess && !installationsQuery.isError ? (
          <p className="text-xs text-muted-foreground">
            Loading GitHub installations…
          </p>
        ) : primaryPickerMode ? (
          <div className="space-y-3 rounded-md border border-border/80 bg-muted/20 p-3">
            <p className="text-xs font-medium text-foreground">
              Choose installation and repository
            </p>
            <div className="space-y-1.5">
              <label
                className="text-xs text-muted-foreground"
                htmlFor="workshop-install-select-trigger"
              >
                GitHub App installation
              </label>
              <Select
                key={sortedInstallRows.map((r) => r.installation_id).join(",")}
                value={installationSelectValue}
                onValueChange={(value) => {
                  setInstallationId(value)
                  persistInstallationPreference(Number.parseInt(value, 10))
                  setFullName("")
                  setErrorDetail(null)
                }}
              >
                <SelectTrigger
                  id="workshop-install-select-trigger"
                  className="w-full"
                  data-testid="workshop-sync-installation-select"
                >
                  <SelectValue placeholder="Select installation…" />
                </SelectTrigger>
                <SelectContent>
                  {sortedInstallRows.map((inst) => (
                    <SelectItem
                      key={inst.installation_id}
                      value={String(inst.installation_id)}
                    >
                      {inst.account_login} · #{inst.installation_id} ·{" "}
                      {inst.repository_selection ?? "unknown"}
                      {inst.suspended ? " · suspended" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedInstallation ? (
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                  <a
                    href={selectedInstallation.installation_settings_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-primary underline"
                  >
                    Open installation on GitHub
                  </a>
                  <button
                    type="button"
                    className="text-primary underline"
                    onClick={() =>
                      void copyInstallationId(
                        selectedInstallation.installation_id,
                      )
                    }
                  >
                    {copiedInstallationId ===
                    selectedInstallation.installation_id
                      ? "Copied ID"
                      : "Copy installation ID"}
                  </button>
                </div>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <label
                className="text-xs text-muted-foreground"
                htmlFor="repo-full-name-primary"
              >
                Repository (owner/name)
              </label>
              {accessibleReposQuery.isFetching &&
              !accessibleReposQuery.isSuccess ? (
                <p className="text-xs text-muted-foreground">
                  Loading repositories GitHub grants this installation…
                </p>
              ) : null}
              {dedupedRepoNameSuggestions.length > 0 ? (
                <p className="text-xs text-muted-foreground">
                  Pick a suggestion or type any owner/repo (including repos not
                  in the list).
                </p>
              ) : null}
              <Input
                id="repo-full-name-primary"
                value={fullName}
                list={
                  dedupedRepoNameSuggestions.length > 0
                    ? repoOwnerNameDatalistId
                    : undefined
                }
                onChange={(e) => {
                  setFullName(e.target.value)
                  setErrorDetail(null)
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && canSubmit) {
                    event.preventDefault()
                    onSubmit()
                  }
                }}
                placeholder="owner/repo (e.g. acme/workshop-lessons)"
                data-testid="workshop-sync-full-name"
              />
              {dedupedRepoNameSuggestions.length > 0 ? (
                <datalist id={repoOwnerNameDatalistId}>
                  {dedupedRepoNameSuggestions.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              ) : null}
              {accessibleReposQuery.isSuccess &&
              repoNameSuggestions.length === 0 &&
              !blockingSetupHint ? (
                <p className="text-xs text-muted-foreground">
                  No repository list from GitHub yet—type owner/repo manually or
                  open install settings and use Refresh lists.
                </p>
              ) : null}
              {accessibleReposQuery.isError &&
              !(
                selectedInstallation?.repository_selection === "selected" &&
                (selectedInstallation.entitled_repositories?.length ?? 0) > 0
              ) ? (
                <p className="text-xs text-destructive">
                  Could not load repository names from GitHub. Check backend
                  credentials and try Refresh lists.
                </p>
              ) : null}
              {accessibleReposQuery.isError &&
              selectedInstallation?.repository_selection === "selected" &&
              (selectedInstallation.entitled_repositories?.length ?? 0) > 0 ? (
                <p className="text-xs text-muted-foreground">
                  Showing saved entitlements; live list from GitHub is
                  unavailable.
                </p>
              ) : null}
              {showRepoValidation ? (
                <p className="text-xs text-destructive">
                  Use owner/repo format, for example{" "}
                  <code>acme/workshop-lessons</code>.
                </p>
              ) : null}
            </div>

            <div className="border-t border-border/60 pt-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-muted-foreground"
                onClick={() => setAdvancedManualOpen((open) => !open)}
                data-testid="workshop-sync-toggle-manual-entry"
              >
                {advancedManualOpen ? "Hide manual entry" : "Manual entry"}
                <span className="text-muted-foreground/80">
                  {" "}
                  (installation ID override)
                </span>
              </Button>
              {advancedManualOpen ? (
                <div className="mt-2 max-w-xs space-y-1">
                  <label
                    className="text-xs text-muted-foreground"
                    htmlFor="installation-id-override"
                  >
                    Installation ID
                  </label>
                  <Input
                    id="installation-id-override"
                    type="number"
                    min={1}
                    value={installationId}
                    onChange={(e) => {
                      const v = e.target.value
                      setInstallationId(v)
                      if (v.trim() === "") {
                        lastAutofillFingerprintForEmpty.current = null
                      }
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && canSubmit) {
                        event.preventDefault()
                        onSubmit()
                      }
                    }}
                    placeholder="12345678"
                    data-testid="workshop-sync-installation-id"
                  />
                  {showInstallationValidation ? (
                    <p className="text-xs text-destructive">
                      Installation ID must be a positive number.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        ) : showManualFallback ? (
          <div className="space-y-2 rounded-md border border-border/80 bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">
              No installations are in app state yet. After you install the
              GitHub App, use Discover / Refresh lists. If you already know the
              numeric installation ID (from the GitHub URL), you can enter it
              here.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <label
                  className="text-xs text-muted-foreground"
                  htmlFor="installation-id"
                >
                  Installation ID
                </label>
                <Input
                  id="installation-id"
                  type="number"
                  min={1}
                  value={installationId}
                  onChange={(e) => {
                    const v = e.target.value
                    setInstallationId(v)
                    if (v.trim() === "") {
                      lastAutofillFingerprintForEmpty.current = null
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && canSubmit) {
                      event.preventDefault()
                      onSubmit()
                    }
                  }}
                  placeholder="12345678"
                  data-testid="workshop-sync-installation-id"
                />
                {showInstallationValidation ? (
                  <p className="text-xs text-destructive">
                    Installation ID must be a positive number.
                  </p>
                ) : null}
              </div>
              <div className="space-y-1">
                <label
                  className="text-xs text-muted-foreground"
                  htmlFor="repo-full-name"
                >
                  Repository (owner/name)
                </label>
                <Input
                  id="repo-full-name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && canSubmit) {
                      event.preventDefault()
                      onSubmit()
                    }
                  }}
                  placeholder="acme/workshop-lessons"
                  data-testid="workshop-sync-full-name"
                />
              </div>
            </div>
            {showRepoValidation ? (
              <p className="text-xs text-destructive">
                Use owner/repo format, for example{" "}
                <code>acme/workshop-lessons</code>.
              </p>
            ) : null}
          </div>
        ) : null}

        {selectedInstallationNeedsGrant && selectedInstallation ? (
          <div
            className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200"
            data-testid="workshop-sync-grant-access-prompt"
          >
            <p className="font-medium">
              Grant repository access before syncing
            </p>
            <p>
              This installation uses selected repositories but none are entitled
              in app state yet. Open GitHub, grant the repo, then refresh.
            </p>
            <a
              href={selectedInstallation.installation_settings_url}
              target="_blank"
              rel="noreferrer noopener"
              className="underline text-primary"
            >
              Grant repository access
            </a>
            <div className="mt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => void refreshCardData()}
                disabled={isBusy}
                data-testid="workshop-sync-refresh-entitlements"
              >
                Refresh entitlements now
              </Button>
            </div>
          </div>
        ) : null}

        {recentRepos.length > 0 ? (
          <div className="space-y-1" data-testid="workshop-sync-recent-repos">
            <p className="text-xs text-muted-foreground">Recent repositories</p>
            <div className="flex flex-wrap gap-2">
              {recentRepos.map((repo) => (
                <Button
                  key={repo}
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => {
                    setFullName(repo)
                    setErrorDetail(null)
                  }}
                >
                  {repo}
                </Button>
              ))}
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
            data-testid="workshop-sync-submit"
          >
            {syncMutation.isPending ? "Syncing..." : "Sync from GitHub"}
          </Button>
          {syncMutation.data ? (
            <span
              className="text-xs text-emerald-600 dark:text-emerald-400"
              data-testid="workshop-sync-success"
            >
              Synced {syncMutation.data.lessons_synced} lesson(s) from{" "}
              {syncMutation.data.full_name}
            </span>
          ) : null}
          {lastRefreshedAt ? (
            <span className="text-xs text-muted-foreground">
              Refreshed {lastRefreshedAt.toLocaleTimeString()}
            </span>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => void refreshCardData()}
            disabled={isBusy}
            data-testid="workshop-sync-refresh"
          >
            {isRefreshingData ? "Refreshing..." : "Refresh lists"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={clearInputs}
            disabled={isBusy}
            data-testid="workshop-sync-clear-inputs"
          >
            Reset
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() =>
              setHealthFilter((prev) => {
                if (prev === "all") return "unhealthy"
                if (prev === "unhealthy") return "healthy"
                return "all"
              })
            }
            disabled={isBusy}
            data-testid="workshop-sync-unhealthy-toggle"
          >
            {healthFilter === "all"
              ? "Show unhealthy only"
              : healthFilter === "unhealthy"
                ? "Show healthy only"
                : "Show all repos"}
          </Button>
          <Input
            value={repoSearch}
            onChange={(event) => setRepoSearch(event.target.value)}
            placeholder="Filter synced repos..."
            className="h-7 w-[220px] text-xs"
            data-testid="workshop-sync-repo-search"
          />
        </div>
        {errorDetail ? (
          <p
            className="text-xs text-destructive"
            data-testid="workshop-sync-error"
          >
            {errorDetail}
          </p>
        ) : null}
        {refreshError ? (
          <p
            className="text-xs text-destructive"
            data-testid="workshop-sync-refresh-error"
          >
            {refreshError}
          </p>
        ) : null}
        <div className="space-y-1 pt-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium">Synced lesson repositories</p>
            <p className="text-xs text-muted-foreground">
              {reposQuery.data?.count ?? 0} repo(s) ·{" "}
              {installationsQuery.data?.count ?? 0} installation(s) ·{" "}
              {freshnessLabel}
            </p>
          </div>
          {reposQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">
              Loading repositories…
            </p>
          ) : reposQuery.isError ? (
            <div className="flex items-center gap-2">
              <p className="text-xs text-destructive">
                Could not load repositories list.
              </p>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => void reposQuery.refetch()}
                disabled={isBusy}
              >
                Retry
              </Button>
            </div>
          ) : (reposQuery.data?.count ?? 0) === 0 ? (
            <p className="text-xs text-muted-foreground">
              No lesson repositories synced yet.
            </p>
          ) : visibleSyncedRepos.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No synced repositories for the selected installation.
            </p>
          ) : (
            <ul className="divide-y rounded-md border text-xs">
              {visibleSyncedRepos.map((repo) => (
                <li
                  key={repo.lesson_repo_id}
                  className="px-2 py-2 flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <p className="font-medium truncate">{repo.full_name}</p>
                    <p className="text-muted-foreground truncate">
                      {repo.default_branch} · {repo.lesson_count} lesson(s) ·{" "}
                      {repo.part_count} part(s) · {repo.manifest_count ?? 0}{" "}
                      manifest(s)
                    </p>
                    <p className="text-muted-foreground truncate">
                      Last sync: {formatSyncTimestamp(repo.last_synced_at)}
                    </p>
                    <p className="text-muted-foreground truncate">
                      Last manifest sync:{" "}
                      {formatSyncTimestamp(repo.last_manifest_synced_at)}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={
                          repo.health === "healthy"
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-amber-600 dark:text-amber-400"
                        }
                      >
                        {repo.health}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        data-testid="workshop-repo-use-lesson"
                        onClick={() =>
                          void handleUseLessonFromRepo(repo.lesson_repo_id)
                        }
                        disabled={previewLoadingRepoId === repo.lesson_repo_id}
                      >
                        {previewLoadingRepoId === repo.lesson_repo_id
                          ? "Loading..."
                          : (() => {
                              const pv = previewByRepoId[repo.lesson_repo_id]
                              const previewLen = pv?.lessons.length ?? 0
                              const effectiveCount =
                                pv !== undefined && previewLen > 0
                                  ? previewLen
                                  : repo.lesson_count
                              return effectiveCount > 1
                                ? "Choose lesson"
                                : "Use lesson"
                            })()}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() =>
                          void toggleRepoPreview(repo.lesson_repo_id)
                        }
                        disabled={previewLoadingRepoId === repo.lesson_repo_id}
                        data-testid="workshop-repo-preview-toggle"
                      >
                        {previewLoadingRepoId === repo.lesson_repo_id
                          ? "Loading..."
                          : expandedPreviewRepoIds[repo.lesson_repo_id]
                            ? "Hide parts"
                            : "Preview parts"}
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {visibleSyncedRepos.map((repo) => {
            if (!expandedPreviewRepoIds[repo.lesson_repo_id]) return null
            const preview = previewByRepoId[repo.lesson_repo_id]
            const previewError = previewErrorByRepoId[repo.lesson_repo_id]
            return (
              <div
                key={`${repo.lesson_repo_id}-preview`}
                className="rounded-md border bg-muted/20 p-2 text-xs"
                data-testid="workshop-repo-preview-panel"
              >
                <p className="font-medium">
                  Parts preview for <code>{repo.full_name}</code>
                </p>
                {previewError ? (
                  <p className="text-destructive">{previewError}</p>
                ) : preview ? (
                  preview.lessons.length > 0 ? (
                    <ul className="mt-1 space-y-2">
                      {preview.lessons.map((lesson) => (
                        <li
                          key={lesson.lesson_id}
                          className="rounded border border-border/60 bg-background/50 p-2"
                        >
                          <p className="font-medium">
                            {lesson.lesson_title} ({lesson.lesson_slug})
                          </p>
                          {lesson.parts.length > 0 ? (
                            <p className="text-muted-foreground">
                              {lesson.parts
                                .map(
                                  (part) =>
                                    `${part.ordering + 1}. ${part.title}`,
                                )
                                .join(" | ")}
                            </p>
                          ) : (
                            <p className="text-muted-foreground">
                              No parts in lesson.
                            </p>
                          )}
                          {preview.lessons.length > 1 ? (
                            <div className="mt-2 flex flex-col items-start gap-1">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                data-testid={`workshop-repo-start-session-${lesson.lesson_id}`}
                                disabled={
                                  previewLoadingRepoId === repo.lesson_repo_id
                                }
                                onClick={() => goToSessionSetupWizard(lesson)}
                              >
                                Start workshop
                              </Button>
                            </div>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground">
                      No lessons synced yet.
                    </p>
                  )
                ) : (
                  <p className="text-muted-foreground">Preview not loaded.</p>
                )}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
