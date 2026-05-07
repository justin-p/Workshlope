import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"

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

const RECENT_REPOS_KEY = "workshop.lessonRepoSync.recentRepos"
const OWNER_REPO_RE = /^[^/\s]+\/[^/\s]+$/
const COPY_ID_FEEDBACK_MS = 1500
const AUTOFILL_FEEDBACK_MS = 2000
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
  const [fullName, setFullName] = useState("")
  const [installationId, setInstallationId] = useState("")
  const [recentRepos, setRecentRepos] = useState<string[]>([])
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [copiedInstallationId, setCopiedInstallationId] = useState<
    number | null
  >(null)
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null)
  const [autofillHint, setAutofillHint] = useState<string | null>(null)
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
  const installCtaHref =
    installationsQuery.data?.install_url ??
    "https://github.com/settings/installations"

  const canSubmit =
    normalizedRepo.length > 0 &&
    repoFormatValid &&
    installationIdValid &&
    Number.isFinite(installationIdInt) &&
    !syncMutation.isPending

  const selectedInstallation = useMemo(() => {
    if (!Number.isFinite(installationIdInt)) return null
    return (
      installationsQuery.data?.data.find(
        (inst) => inst.installation_id === installationIdInt,
      ) ?? null
    )
  }, [installationIdInt, installationsQuery.data?.data])

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
    if (errorDetail) return `Sync failed: ${errorDetail}`
    if (syncMutation.data) {
      return `Last sync succeeded for ${syncMutation.data.full_name}.`
    }
    return "Ready to sync from GitHub."
  }, [errorDetail, isRefreshingData, syncMutation.data, syncMutation.isPending])

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

  const applyInstallationAndRepo = (
    installationIdValue: number,
    repoName: string,
  ) => {
    setInstallationId(String(installationIdValue))
    setFullName(repoName)
    setErrorDetail(null)
    setAutofillHint(
      `Autofilled ${repoName} with installation #${installationIdValue}.`,
    )
    setTimeout(() => setAutofillHint(null), AUTOFILL_FEEDBACK_MS)
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

  const refreshCardData = async () => {
    await Promise.all([reposQuery.refetch(), installationsQuery.refetch()])
    setLastRefreshedAt(new Date())
  }

  const clearInputs = () => {
    setFullName("")
    setInstallationId("")
    setErrorDetail(null)
    setAutofillHint(null)
  }

  const loadRepoPreview = async (repoId: string) => {
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
        return
      }
      setPreviewByRepoId((prev) => ({
        ...prev,
        [repoId]: body as LessonRepoPreview,
      }))
      setExpandedPreviewRepoIds((prev) => ({ ...prev, [repoId]: true }))
    } catch {
      setPreviewErrorByRepoId((prev) => ({
        ...prev,
        [repoId]: "Could not load preview",
      }))
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
          Need to install or adjust repository access first? Open{" "}
          <a
            href={installCtaHref}
            target="_blank"
            rel="noreferrer noopener"
            className="underline text-primary"
          >
            GitHub App installations
          </a>
          .
        </p>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {statusMessage}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
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
            {showRepoValidation ? (
              <p className="text-xs text-destructive">
                Use owner/repo format, for example{" "}
                <code>acme/workshop-lessons</code>.
              </p>
            ) : null}
          </div>
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
              onChange={(e) => setInstallationId(e.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && canSubmit) {
                  event.preventDefault()
                  onSubmit()
                }
              }}
              placeholder="12345678"
              data-testid="workshop-sync-installation-id"
              list="workshop-installation-ids"
            />
            <datalist id="workshop-installation-ids">
              {(installationsQuery.data?.data ?? []).map((inst) => (
                <option
                  key={inst.installation_id}
                  value={String(inst.installation_id)}
                />
              ))}
            </datalist>
            {showInstallationValidation ? (
              <p className="text-xs text-destructive">
                Installation ID must be a positive number.
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Find this in the GitHub App installation URL.
            </p>
            {installationsQuery.isSuccess &&
            (installationsQuery.data?.count ?? 0) > 0 ? (
              <p className="text-xs text-muted-foreground">
                Known installations: {installationsQuery.data?.count}
              </p>
            ) : null}
            {installationsQuery.isError ? (
              <div className="flex items-center gap-2">
                <p className="text-xs text-destructive">
                  Could not load installations.
                </p>
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
          </div>
        </div>
        {installationsQuery.isSuccess &&
        (installationsQuery.data?.count ?? 0) > 0 ? (
          <div
            className="space-y-1"
            data-testid="workshop-installation-options"
          >
            <p className="text-xs text-muted-foreground">
              Installation options
            </p>
            <div className="flex flex-wrap gap-2">
              {installationsQuery.data?.data.map((inst) => (
                <div
                  key={inst.installation_id}
                  className="flex items-center gap-1"
                >
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => {
                      setInstallationId(String(inst.installation_id))
                      setErrorDetail(null)
                    }}
                  >
                    {inst.account_login}#{inst.installation_id} ·{" "}
                    {inst.repository_selection ?? "unknown"}
                    {inst.suspended ? " · suspended" : ""}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() =>
                      void copyInstallationId(inst.installation_id)
                    }
                    title="Copy installation ID"
                  >
                    {copiedInstallationId === inst.installation_id
                      ? "Copied"
                      : "Copy ID"}
                  </Button>
                  <a
                    href={inst.installation_settings_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-xs text-primary underline"
                  >
                    Open settings
                  </a>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {selectedInstallation ? (
          <div
            className="space-y-1"
            data-testid="workshop-selected-installation-meta"
          >
            <p className="text-xs text-muted-foreground">
              Selected installation:{" "}
              <span className="font-medium text-foreground">
                {selectedInstallation.account_login}#
                {selectedInstallation.installation_id}
              </span>{" "}
              ({selectedInstallation.repository_selection ?? "unknown"} access)
            </p>
            {selectedInstallation.repository_selection === "selected" ? (
              selectedInstallation.entitled_repositories.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {selectedInstallation.entitled_repositories.map((repo) => (
                    <Button
                      key={repo}
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => {
                        applyInstallationAndRepo(
                          selectedInstallation.installation_id,
                          repo,
                        )
                      }}
                    >
                      {repo}
                    </Button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  This installation is set to selected repositories but
                  currently has no entitled repos in app state.
                </p>
              )
            ) : null}
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
            Clear inputs
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
        {autofillHint ? (
          <p
            className="text-xs text-muted-foreground"
            data-testid="workshop-sync-autofill-hint"
          >
            {autofillHint}
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
                  <div className="flex items-center gap-2">
                    {/*
                      Keep "Use" aligned with current filter context to avoid
                      accidental cross-installation prefills.
                    */}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() =>
                        applyInstallationAndRepo(
                          repo.github_installation_id ?? installationIdInt,
                          repo.full_name,
                        )
                      }
                      disabled={
                        !repo.github_installation_id ||
                        (selectedInstallation !== null &&
                          repo.github_installation_id !==
                            selectedInstallation.installation_id)
                      }
                      title={
                        selectedInstallation !== null &&
                        repo.github_installation_id !==
                          selectedInstallation.installation_id
                          ? "Repo belongs to a different installation"
                          : undefined
                      }
                    >
                      Use
                    </Button>
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
                    <ul className="mt-1 space-y-1">
                      {preview.lessons.map((lesson) => (
                        <li key={lesson.lesson_id}>
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
