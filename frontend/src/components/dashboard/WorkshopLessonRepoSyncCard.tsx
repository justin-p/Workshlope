import { useMutation, useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

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

export function WorkshopLessonRepoSyncCard() {
  const [fullName, setFullName] = useState("")
  const [installationId, setInstallationId] = useState("")
  const [recentRepos, setRecentRepos] = useState<string[]>([])
  const [errorDetail, setErrorDetail] = useState<string | null>(null)

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
    onSuccess: () => {
      setErrorDetail(null)
      const normalized = fullName.trim()
      if (OWNER_REPO_RE.test(normalized)) {
        const next = [
          normalized,
          ...recentRepos.filter((r) => r !== normalized),
        ].slice(0, 5)
        setRecentRepos(next)
        try {
          localStorage.setItem(RECENT_REPOS_KEY, JSON.stringify(next))
        } catch {
          // Ignore localStorage write failures in private/locked contexts.
        }
      }
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

  const reposQuery = useQuery({
    queryKey: ["workshopLessonRepos"],
    queryFn: () =>
      WorkshopLessonReposService.readLessonRepos({
        skip: 0,
        limit: 20,
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

  const canSubmit =
    normalizedRepo.length > 0 &&
    repoFormatValid &&
    installationIdValid &&
    Number.isFinite(installationIdInt) &&
    !syncMutation.isPending

  const onSubmit = () => {
    if (!canSubmit) return
    syncMutation.mutate({
      full_name: fullName.trim(),
      installation_id: installationIdInt,
    })
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
            href="https://github.com/settings/installations"
            target="_blank"
            rel="noreferrer noopener"
            className="underline text-primary"
          >
            GitHub App installations
          </a>
          .
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
                <Button
                  key={inst.installation_id}
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => {
                    setInstallationId(String(inst.installation_id))
                    setErrorDetail(null)
                  }}
                >
                  {inst.account_login}#{inst.installation_id}
                  {inst.suspended ? " (suspended)" : ""}
                </Button>
              ))}
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
        </div>
        {errorDetail ? (
          <p
            className="text-xs text-destructive"
            data-testid="workshop-sync-error"
          >
            {errorDetail}
          </p>
        ) : null}
        <div className="space-y-1 pt-2">
          <p className="text-xs font-medium">Synced lesson repositories</p>
          {reposQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">
              Loading repositories…
            </p>
          ) : reposQuery.isError ? (
            <p className="text-xs text-destructive">
              Could not load repositories list.
            </p>
          ) : (reposQuery.data?.count ?? 0) === 0 ? (
            <p className="text-xs text-muted-foreground">
              No lesson repositories synced yet.
            </p>
          ) : (
            <ul className="divide-y rounded-md border text-xs">
              {reposQuery.data?.data.map((repo) => (
                <li
                  key={repo.lesson_repo_id}
                  className="px-2 py-2 flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <p className="font-medium truncate">{repo.full_name}</p>
                    <p className="text-muted-foreground truncate">
                      {repo.default_branch} · {repo.lesson_count} lesson(s) ·{" "}
                      {repo.part_count} part(s)
                    </p>
                  </div>
                  <span
                    className={
                      repo.health === "healthy"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-amber-600 dark:text-amber-400"
                    }
                  >
                    {repo.health}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
