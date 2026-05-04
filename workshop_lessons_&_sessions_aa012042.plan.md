---
name: Workshop Lessons & Sessions
overview: "Living delivery status: scroll to **Implementation tracker** and **[Pause / resume checkpoint](#pause--resume-checkpoint-handoff)** after a stop. Update the tracker whenever a stacked PR slice merges or behavior changes materially."
todos:
  - id: role-instructor
    content: User.is_instructor + RBAC — superuser has full workshop/session management APIs; instructors own sessions or any session where they are assigned as instructor/rostered participant; gate GitHub App install prompts to instructor-only surfaces
    status: pending
  - id: github-app-sync
    content: GitHub App; webhooks (signature, throttle, optional delivery idempotency); installs/repos; PEM + installation tokens; instructor-bound LessonRepo entitlement; post-MVP push webhook optional
    status: pending
  - id: lesson-sync-model
    content: LessonRepo/Lesson/LessonPart with per-lesson YAML manifest ordering; idempotent sync; hard-fail invalid manifest with unhealthy repo; sanitize Markdown on render and rewrite relative assets to GitHub raw URLs
    status: pending
  - id: session-progress
    content: WorkshopSession lifecycle + SessionInstructor join table; WorkshopParticipant; enter REST; add-member role assignment is mutually exclusive with always-replace semantics; pause/handoff; no finished_at on end
    status: pending
  - id: ws-live
    content: ws-ticket via Sec-WebSocket-Protocol; part_generation reconnect; pause gates; trainee WS/API payloads omit peer identities and peer live_status (instructor-only fanout full roster)
    status: pending
  - id: replace-items-nav
    content: "Dashboard nav + **`GET /workshop/sessions/`** list widgets + **`GET /workshop/sessions/{id}`** cockpit heading — shipped on **`ws-05-dashboard-nav` / [#22](https://github.com/justin-p/testing/pull/22)**; stack merge pending. **Paused 2026-05-04** — resume from [Pause / resume checkpoint](#pause--resume-checkpoint-handoff)."
    status: completed
  - id: badges-awards
    content: Instructor-verified badge issuance on completion (single + bulk); badge catalog + user badge grants with per-badge points; profile/session/instructor surfaces + public leaderboard
    status: pending
  - id: attendance-analytics
    content: "Instructor analytics dashboards: join delay, completion rate, time-to-finish distributions, pause frequency, per-session and cross-session trends"
    status: pending
  - id: badge-revocation
    content: Badge revoke workflow with reason + audit trail + optional learner-visible rationale; leaderboard/profile updates on revoke
    status: pending
  - id: instructor-notes
    content: Private instructor notes per lesson/session with searchable history and non-trainee visibility guarantees
    status: pending
  - id: prework-prerequisites
    content: Prework and prerequisite checklist per lesson with completion tracking and session gating warnings
    status: pending
  - id: attendance-exports
    content: Attendance exports (CSV) with joined/finished/delay/badge columns and cohort filters
    status: pending
  - id: cohorts-teams
    content: Cohorts/teams model with assignment, filtering, and cohort-level analytics slices
    status: pending
  - id: reminders-automation
    content: In-app reminder automation for upcoming sessions and pause/resume transitions
    status: pending
  - id: pacing-tools
    content: Session timer and pacing tools (part timer, overrun indicators, instructor controls)
    status: pending
  - id: learner-feedback
    content: End-of-session learner reflection/feedback capture and instructor review dashboard
    status: pending
  - id: security-hardening-new-features
    content: Security hardening for notes/prereqs/cohorts/reminders/timers/feedback/exports (RBAC, anti-abuse, audit, privacy thresholds, CSV injection protections)
    status: pending
isProject: false
---

# Workshop training app — lessons + live sessions

## Out of scope (MVP)


| Area                 | Decision                                                               |
| -------------------- | ---------------------------------------------------------------------- |
| Messaging            | No chat, no DMs, no in-session threads. Only busy/done pacing signals. |
| Guests / magic links | No. Participants must be existing app users on the session roster.     |
| Video / screen-share | No integrated A/V in the app; use external tools if needed.            |


## Product constraints

- **Lesson source**: GitHub via a **GitHub App** (installation tokens from PEM; Contents + Metadata read as tight as practical). **Auth.js / OAuth** is **login and identity only** — not used to carry repo-scoped user tokens for sync.
- **Install prompt visibility**: Only users with **is_instructor=true** are shown GitHub App install/configure prompts. Non-instructors never see install CTAs/routes, and backend install-related endpoints enforce instructor authorization (403 for others).
- **Superuser authority**: Superusers have full instructor-equivalent control for workshop/session management APIs. GitHub App install/config prompts remain hidden unless `is_instructor=true`.
- **Session–lesson binding**: Each **WorkshopSession** uses exactly one **Lesson**. Instructor controls the **current instructional part** (index + **slug** mirror on the session).
- **Roster**: Instructor manages **WorkshopParticipant** rows (add/remove; soft-remove with **removed_at**). GitHub avatars are used across application identity surfaces when available; trainee session payloads still exclude peer identities/avatars.
- **Signals**: **live_status** = busy | done for the **current part**, shown **only to that user and to instructors** — **trainees must not see other trainees’ status**, roster, joined/finished timestamps, or presence (privacy + reduces comparison anxiety). Instructor cockpit remains the aggregate view.
- **Pause**: No participant busy/done writes; **no part navigation** (no **part_generation** bump) until **resume** or **end**.
- **Awards**: Badge grants are issued **only after instructor verification** of completion (not immediately on trainee self-finish), and surfaced across profile, session views, instructor views, and a global leaderboard.
- **Analytics**: Instructor-facing attendance analytics are part of scope (session and aggregate metrics). Badge revocation workflows are also in scope with auditable reasons.
- **Instructor notes**: Private instructor-only notes are supported at lesson and session level; never exposed to trainees.
- **Prework/prerequisites**: Lessons can define prerequisite tasks; trainee completion is tracked and surfaced before session start.
- **Cohorts/teams**: Participants can be grouped into cohorts/teams for roster filtering and analytics breakdowns.
- **Reminder automation**: In-app reminders are automatically sent for upcoming starts and pause/resume changes.
- **Pacing tools**: Session timer controls (per-part countdown/elapsed and overrun flags) are instructor-facing.
- **Feedback**: End-of-session learner reflection/feedback is captured and available to instructors in aggregate and per-session views.
- **Backend delivery method**: Use `/python-tdd-with-uv` workflow across the entire backend implementation (test-first, vertical slices, `uv run pytest` loop).

## Delivery methodology (locked)

Apply `/python-tdd-with-uv` for all Python backend changes in this plan:

- **TDD cycle required:** RED (one failing test) -> GREEN (minimum code) -> REFACTOR.
- **One behavior at a time:** never implement a backend behavior without a failing test first.
- **Execution command standard:** use `uv run` for Python commands; do not rely on manual venv activation.
- **Test gate per slice:** run relevant tests after each slice (`uv run pytest ...`) before moving to the next slice.
- **Dependency/tooling standard:** manage Python deps/test tools with `uv` (`pyproject.toml` + `uv.lock` kept in sync).
- **Scope note:** this methodology is mandatory for backend Python code; frontend follows existing TS/Playwright workflow.
- **E2E quality gate:** maintain full Playwright end-to-end coverage for implemented user journeys (instructor + trainee + admin paths where applicable).

### Definition of Done per implementation slice

- A single next behavior is defined and covered by a new failing test first (RED).
- Minimal code is added to satisfy only that behavior (GREEN).
- Relevant tests are run with `uv run pytest` and pass before proceeding.
- Refactor is completed without behavior change (tests remain green).
- Security/rbac/privacy assertions for that slice are included where applicable.
- API slice changes include updated OpenAPI and regenerated TS client artifacts when contract changed.
- New or changed user flows have corresponding Playwright E2E coverage (happy path + key permission/privacy guards).
- Critical role/privacy/security behavior is validated in E2E before the slice is considered complete.
- Docs/plan check: update affected plan/testing notes if scope or constraints evolved.

## Implementation tracker (canonical — update whenever context would otherwise be lost)

This section is the **recoverable checklist** when chat history or IDE session is gone. Prefer editing here over relying on conversational memory.

**Maintenance rule:** After each meaningful backend/frontend/E2E slice, update **Last synced**, the **Active branch / PR**, toggle ✅ / 🔲 in the matrices below, and keep **[GitHub PR stack](#github-pr-stack-open--update-when-retargetedmerged)** in sync (new PR, merge, or base-branch change). For the open **tip** PR, run a **babysit loop** (see [Next actions](#next-actions-suggested-order)): `gh pr checks` / `gh pr checks --watch`, `gh run view --log-failed` on failures, fix + push on that PR’s head branch (≤3 remediation rounds per **babysitting-pr** Cursor skill — or an equivalent **Task** subagent mirroring `gh pr checks` → fix → push).

| Field | Value |
| ------ | ------ |
| **Last synced** | **2026-05-04 — intentional pause.** **`ws-05-dashboard-nav`** @ **`308b8e6`** (includes pause handoff doc). Older feature tip: **`e90450d`**. Jump to [Pause / resume checkpoint](#pause--resume-checkpoint-handoff). |
| **Active integration branch** | `ws-05-dashboard-nav` → [PR #22](https://github.com/justin-p/testing/pull/22) (base `ws-04-realtime-privacy`). **Successor branch:** `ws-06-learning-workflows` (*not created until PR06 slice starts*) |
| **Stack PR label** | **PR05 — DashboardNav** ✅ on branch; **`main`** after stacked merge (**#18** → … → **#22**) or retarget per [stack table](#github-pr-stack-open--update-when-retargetedmerged) |

### Pause / resume checkpoint (handoff)

Use this section when reopening the project **after intentional stop**. Do **not** rely on chat history beyond what is committed and linked here.

**Stopped:** 2026-05-04.

**Git tip (must match when resuming work on this slice):**

| Item | Value |
| ---- | ----- |
| Branch | `ws-05-dashboard-nav` |
| Latest commits (newest → older) | `308b8e6` — this **pause handoff** update ← `e90450d` ← `de9f1c5` (GET detail) ← `2f85219` (dashboard list UI) ← `20f8e0f` (GET list API) ← … |
| PR | [#22](https://github.com/justin-p/testing/pull/22) (base `ws-04-realtime-privacy`) |

**Shipped on this branch since last stack merge expectation:**

- **`GET /api/v1/workshop/sessions/`** — scoped list (`WorkshopSessionsPublic`); dashboards + `/workshops` use [`DashboardWorkshopSessions`](frontend/src/components/dashboard/DashboardWorkshopSessions.tsx) + `WorkshopSessionsService.readWorkshopSessionsForUser`.
- **`GET /api/v1/workshop/sessions/{id}`** — participant vs instructor DTOs (`WorkshopSessionPublicParticipant` \| `WorkshopSessionPublicInstructor`); superuser ⇒ instructor-shaped view; roster **`avatar_url`** is always **`null`** until **`User.avatar_url`** exists in schema.
- **`/workshop/$sessionId`** — hydrates lesson **title/slug** via `WorkshopSessionsService.readWorkshopSessionDetail` (`useQuery`), then existing ws-ticket/WebSocket flow.
- **Tests:** new cases in [`test_workshop_sessions.py`](backend/tests/api/routes/test_workshop_sessions.py) for detail; full file was green at pause (`uv run pytest tests/api/routes/test_workshop_sessions.py`).
- **Client:** regenerated under [`frontend/src/client/`](frontend/src/client/) whenever OpenAPI changed (pre-commit `generate-frontend-sdk`).

**Resume in this order:**

1. `git checkout ws-05-dashboard-nav && git pull`, then **`gh pr checks 22`** (or CI dashboard) — fix regressions on the **same head branch** if needed.
2. Proceed with **[Next actions](#next-actions-suggested-order)** — note item 4 is updated: HTTP gap slices **(1)-(2)** are **done** on this branch; next vertical work is roster sketch / **PR06** prerequisites unless you reorder the stack.
3. When starting **PR06**: fork **`ws-06-learning-workflows`** from current **`ws-05`** tip (or from **`main`** if #18–#22 have landed), update [GitHub PR stack](#github-pr-stack-open--update-when-retargetedmerged) + mermaid dependency graph nodes.

**Open gaps (not blocking pause):**

- Local Playwright **`auth.setup`** can time out without backend/`scripts/e2e-backend-reset.sh` — CI remains source of truth for E2E until env is reproduced locally.
- **Roster `POST/PATCH`** and **prerequisite** endpoints from REST sketch remain 🔲 ([gap audit](#workshop-http-vs-realtime--delivery-gap-audit)).
- Optional: expand Playwright coverage for trainee/instructor **dashboard list** widgets (beyond current admin assertion in `dashboard-routing.spec.ts`).

### GitHub PR stack (open — update when retargeted/merged)

Canonical mapping for [`justin-p/testing`](https://github.com/justin-p/testing). **Head → base** matches the locked stack model. When a PR merges, remove or mark it merged here and add the next open PR for that slice if you split/reopen.

| Slice | Branch (head) | Pull request | Base branch |
| ----- | --------------- | ------------ | ----------- |
| PR01 | `ws-01-foundation-rbac` | [#18](https://github.com/justin-p/testing/pull/18) | `main` |
| PR02 | `ws-02-github-sync-manifest` | [#19](https://github.com/justin-p/testing/pull/19) | `ws-01-foundation-rbac` |
| PR03 | `ws-03-session-core` | [#20](https://github.com/justin-p/testing/pull/20) | `ws-02-github-sync-manifest` |
| PR04 | `ws-04-realtime-privacy` | [#21](https://github.com/justin-p/testing/pull/21) | `ws-03-session-core` |
| PR05 | `ws-05-dashboard-nav` | [#22](https://github.com/justin-p/testing/pull/22) | `ws-04-realtime-privacy` |
| PR06–PR10 | `ws-06-*` … `ws-10-*` | *not opened yet* | *(next PR targets prior branch when created)* |

### Backend code anchors (workshop realtime slice)

| Area | Primary paths |
| ---- | ------------- |
| HTTP + WebSocket routes | [`backend/app/api/routes/workshop_sessions.py`](backend/app/api/routes/workshop_sessions.py) |
| In-memory fan-out hub | [`backend/app/services/workshop_realtime.py`](backend/app/services/workshop_realtime.py) |
| API tests | [`backend/tests/api/routes/test_workshop_sessions.py`](backend/tests/api/routes/test_workshop_sessions.py) |
| Hub unit tests | [`backend/tests/services/test_workshop_realtime.py`](backend/tests/services/test_workshop_realtime.py) |
| Local E2E session bootstrap (`ENVIRONMENT=local` only) | [`backend/app/api/routes/private.py`](backend/app/api/routes/private.py) — `bootstrap_e2e_workshop_live_session` |
| Trainee workshop UI (enter + ws-ticket + WebSocket) | [`frontend/src/routes/_layout/workshop.$sessionId.tsx`](frontend/src/routes/_layout/workshop.$sessionId.tsx) |
| Workshop Playwright | [`frontend/tests/workshop.spec.ts`](frontend/tests/workshop.spec.ts) |
| Dashboard landing + routing | [`frontend/src/lib/dashboardLanding.ts`](frontend/src/lib/dashboardLanding.ts), stub rails [`frontend/src/components/dashboard/DashboardStubRails.tsx`](frontend/src/components/dashboard/DashboardStubRails.tsx), routes under [`frontend/src/routes/_layout/dashboard/`](frontend/src/routes/_layout/dashboard/), [`frontend/src/routes/_layout/workshops.tsx`](frontend/src/routes/_layout/workshops.tsx), sidebar [`frontend/src/components/Sidebar/AppSidebar.tsx`](frontend/src/components/Sidebar/AppSidebar.tsx), OAuth landing [`frontend/src/routes/auth.callback.tsx`](frontend/src/routes/auth.callback.tsx) |
| Playwright harness (backend reset / env) | [`scripts/e2e-backend-reset.sh`](scripts/e2e-backend-reset.sh), [`frontend/playwright.global-setup.ts`](frontend/playwright.global-setup.ts), [`frontend/playwright.config.ts`](frontend/playwright.config.ts) |

### Workshop HTTP vs realtime — delivery gap (audit)

**Canonical router:** [`backend/app/api/routes/workshop_sessions.py`](backend/app/api/routes/workshop_sessions.py).

| Surface | Implemented today | Still 🔲 vs **REST sketch** (below, *REST sketch under /api/v1/*) |
| ------- | ----------------- | ---------------------------------------------------------------- |
| **HTTP** | `POST …/sessions/{id}/enter`, `/start`, `/end`, `/ws-ticket`; **`GET …/sessions/`** list (`WorkshopSessionsPublic`); **`GET …/sessions/{id}`** scoped detail (**`WorkshopSessionPublicParticipant`** \| **`WorkshopSessionPublicInstructor`**) | Roster **`POST/PATCH`**; prerequisites; exports — see sketch table |
| **WebSocket** | `/{id}/ws` — `part.advance`, `session.pause` / `session.resume`, `participant.live_status`, … | Redis / multi-process hub (explicitly deferred) |

**Remaining vs dashboard/product polish:** roster management + prerequisites/export paths in the sketch are still 🔲 (list + read/detail for session context are ✅ on **`ws-05-dashboard-nav`**).

**Suggested vertical slices (backend `/python-tdd-with-uv` first):**

1. **`GET /workshop/sessions/` (scoped list)** — ✅ **`WorkshopSessionsPublic`** on **`ws-05-dashboard-nav`** — participant/instructor seats + optional **`my_role`**; superuser sees all with **`my_role`** null when unseated.
2. **`GET /workshop/sessions/{id}`** — ✅ **`WorkshopSessionPublicParticipant`** (lesson + ordered part metadata + **`self`**) vs **`WorkshopSessionPublicInstructor`** (+ **`participants`** / **`instructors`** roster rows with **`avatar_url`** placeholder `null` until stored on **`User`**); superuser ⇒ instructor-shaped view — matches ws-ticket elevation.
3. **PR06 prerequisites** — `LessonPrerequisite` / `UserPrerequisiteCompletion` and lesson prerequisite routes from the same REST sketch section.

Gate: regenerate **OpenAPI** + **`frontend/src/client`** on every new HTTP route.

### PR04 (`ws-04-realtime-privacy`) — detailed status

Aligned with plan bullets: ws-ticket, role-scoped fan-out, trainee privacy.

| Capability | Status | Notes |
| ---------- | ------ | ----- |
| `POST …/ws-ticket` JWT + claims (`sid`, `uid`, `role`, `pg`) | ✅ | |
| WS auth via `Sec-WebSocket-Protocol: ticket,<jwt>` | ✅ | |
| Handshake rejects non-`live`/`paused` session and wrong `part_generation` | ✅ | |
| Trainee→instructor-only `participant.live_status` fan-out | ✅ | Trainees never receive peer roster payloads on this channel |
| Instructor `part.advance` (live only); bumps `part_generation`; `session.part_changed` to room | ✅ | |
| Instructor `session.pause` / `session.resume` + `session.status_changed` broadcast | ✅ | |
| Trainee `live_status` WS **only when session status is `live`** (blocked while `paused`) | ✅ | Pause matrix |
| Instructor `POST …/start` (`scheduled→live`) + hub broadcast | ✅ | |
| Instructor `POST …/end` (`live`\|`paused→ended`) + hub broadcast | ✅ | Does not bulk-set `finished_at` |
| Enter + ws-ticket reject `scheduled` / `ended` with clear HTTP errors | ✅ | |
| OpenAPI + regenerated TS client when HTTP contract changed | ✅ | Run pre-commit hook on API edits |
| **`part_generation` mirror + stale teardown** (hub sync after advance; **`part_generation_stale`** payload then close **`1008`**; receive loop stops — mint new ws-ticket and reconnect) | ✅ | `_dispatch_workshop_ws_text` returns `False`; `sync_bump_room_part_generation` after advance commit |
| **Multi-process realtime** (Redis or equivalent hub) | 🔲 | MVP is in-memory `WorkshopRealtimeHub` |
| **Playwright** for instructor + trainee flows on these APIs | ✅ | Bounded PR04 cockpit: `/workshop/:id` only — **start / pause / resume / advance / end** smoke + two-user **participant.live_status** fan-out to instructor + explicit trainee denial of same roster-style payload |

### PR05 (`ws-05-dashboard-nav`) — slice status (integration branch ✅, merge pending)

All rows below reflect **`ws-05-dashboard-nav` / [#22](https://github.com/justin-p/testing/pull/22)**. Roll-up **`main`** ✅ only after this PR (or retargeted equivalent) merges.

| Capability | Status | Notes |
| ---------- | ------ | ----- |
| Post-login landing rules (`is_instructor` → Instructor Home; superuser-only → Admin Home; else My Learning) | ✅ | [`getDashboardLandingPath`](frontend/src/lib/dashboardLanding.ts) |
| Routes `/dashboard/instructor`, `/dashboard/trainee`, `/dashboard/admin` + role guards in `beforeLoad` | ✅ | Placeholder dashboards + `dashboard-home-root` testid |
| `/` redirects to role dashboard when logged in; login mutation navigates to landing path | ✅ | Avoids fragile blank `/` after `readUserMe` |
| Sidebar: primary home label/path by role; **Workshops** stub (`/workshops`) for instructor/superuser; **Admin** → `/admin` | ✅ | Items removed from default nav |
| Playwright: `dashboard-routing.spec.ts`, login/auth paths updated for dashboards | ✅ | Shared `loggedInDashboard` + Sonner toast helper for admin/items/settings resets |
| Static **stub rails** on each dashboard (privacy-safe copy + “Soon” cues; trainee has no Workshops link) | ✅ | [`DashboardStubRails.tsx`](frontend/src/components/dashboard/DashboardStubRails.tsx) |
| Sidebar item **active** when path matches or is under same prefix | ✅ | e.g. future `/dashboard/trainee/*` highlights My Learning |
| OAuth **GitHub bridge** navigates to role dashboard (parity with password login) | ✅ | Clears token if `/users/me` fails |
| Live **widgets** wired to workshop session **list + read/detail** APIs | 🟨 | Dashboard list ✅; cockpit uses **GET `{id}`** for lesson heading; sketch roster/prereqs still 🔲 |

### PR06 (`ws-06-learning-workflows`) — planned next slice (*PR not opened*)

Fork from **`ws-05-dashboard-nav`** (or **`main`** after stack lands). Aligns with [Branch/PR chain](#branchpr-chain) item 6 and the frontmatter roadmap id **`prework-prerequisites`**. **HTTP gap slices (1)-(2)** (list + session detail **`GET`s**) landed on **`ws-05-dashboard-nav`** ([gap audit](#workshop-http-vs-realtime--delivery-gap-audit)); PR06 focuses on prerequisites / prework UX and downstream APIs, unless you carve roster management paths first.

| Planned capability | Notes |
| ------------------ | ----- |
| **Session list + detail GETs** | List + **`GET …/{id}`** ✅ on **`ws-05-dashboard-nav`** per [delivery gap audit](#workshop-http-vs-realtime--delivery-gap-audit); prerequisites + richer dashboard cards remain PR06. |
| **Prerequisite / prework** data model | Per-lesson checklist; completion tracking linked to **`User`** and **Lesson**/session context; secure-by-default DTOs ([**Data model (illustrative)**](#data-model-illustrative) — `LessonPrerequisite`, `UserPrerequisiteCompletion`). |
| Trainee UX | Pre-session **warnings / gating hints** where prerequisites incomplete (no trainee peer leakage). |
| Instructor visibility | Scoped view of cohort prerequisite status (details TBD in slice RFC). |
| Tests | **`/python-tdd-with-uv`** backend; Playwright flows for trainee + instructor when UI ships. |
| Stack hygiene | Open **PR #TBD** with base **`ws-05-dashboard-nav`** (or retarget after #22 merges); add row to [GitHub PR stack](#github-pr-stack-open--update-when-retargetedmerged) + mermaid **PR06** node. |

### Stacked PRs — coarse roll-up

Use ✅ when the slice is merged to **`main`** (or materially complete on its integration branch if pre-merge). Use 🟨 for partial. **GitHub:** see [PR stack table](#github-pr-stack-open--update-when-retargetedmerged) for current numbers and bases.

| # | Branch (plan name) | GitHub PR | Status | Notes |
| - | ------------------ | --------- | ------ | ----- |
| 01 | `ws-01-foundation-rbac` | [#18](https://github.com/justin-p/testing/pull/18) | 🟨 | `User.is_instructor` + migrations; confirm against `main` |
| 02 | `ws-02-github-sync-manifest` | [#19](https://github.com/justin-p/testing/pull/19) | 🔲 | GitHub App + manifest sync not tracked here yet |
| 03 | `ws-03-session-core` | [#20](https://github.com/justin-p/testing/pull/20) | 🟨 | Tables + enter semantics overlap with current branch; roster APIs may still be incomplete |
| 04 | `ws-04-realtime-privacy` | [#21](https://github.com/justin-p/testing/pull/21) | 🟨 | Bounded realtime/privacy + `/workshop` E2E ✅ |
| 05 | `ws-05-dashboard-nav` | [#22](https://github.com/justin-p/testing/pull/22) | 🟨 | Routing + dashboards + **`GET`** list/detail + cockpit title hydrate; stacked merge pending ([PR05 table](#pr05-ws-05-dashboard-nav--slice-status-integration-branch--merge-pending)). |
| 06–10 | `ws-06-*` … `ws-10-*` | — | 🔲 | Branches/PRs in [Branch/PR chain](#branchpr-chain); open PRs when slicing |

### Next actions (suggested order)

1. **Confirm tip CI:** `gh pr checks 22` — if anything regresses, run **babysitting-pr** / Task fix loop on `ws-05-dashboard-nav`.
2. **Stack merge:** review + land [#18](https://github.com/justin-p/testing/pull/18) → … → [#22](https://github.com/justin-p/testing/pull/22) (or retarget heads after each base merges to `main`); update [GitHub PR stack](#github-pr-stack-open--update-when-retargetedmerged) after each merge.
3. **PR06 kickoff:** create `ws-06-learning-workflows` from merged tip (or from `ws-05` if stacking without waiting for `main`); follow [PR06 planned slice](#pr06-ws-06-learning-workflows--planned-next-slice-pr-not-opened); open PR + stack table row.
4. **Next backend verticals (gap audit):** slices **(1)-(2)** are ✅ on **`ws-05-dashboard-nav`**. Prefer next: roster **`POST/PATCH`** / participant management aligned with this doc’s [**REST sketch**](#rest-sketch-under-apiv1) section, **or** jump to **PR06** prerequisite models + routes (`LessonPrerequisite`, `UserPrerequisiteCompletion`). *(If that anchor breaks in your renderer, scroll to heading **REST sketch (under /api/v1/…)***.)
5. **E2E discipline:** `scripts/e2e-backend-reset.sh` before full local Playwright when diagnosing drift; Sonner-aware toasts ([playwright-local-gate](.cursor/skills/playwright-local-gate/SKILL.md)).

**When resuming from pause:** step through [Pause / resume checkpoint](#pause--resume-checkpoint-handoff) first.

### YAML todos above

The YAML `todos` list in the frontmatter is a **high-level roadmap** for Cursor/project tooling; it is not automatically synchronized with commits. **`Implementation tracker`** is the authoritative narrative for shipped vs remaining behavior.

## Locked decisions


| Topic                   | Decision                                                                                                                                                                                                                                                                                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Roster vs invite        | Single **WorkshopParticipant** table (**no WorkshopInvite**); **invited_at** when rostered. Instructor-flagged users may also be added here when chosen as trainees.                                                                                                                                                                    |
| joined_at               | **POST …/sessions/{id}/enter** when status is **live** or **paused** only; **not** when **scheduled**. Idempotent. WebSocket does not set joined_at.                                                                                                                                                                                    |
| Session end             | Moves session to **ended** only; **does not** bulk-set **finished_at**.                                                                                                                                                                                                                                                                 |
| Part change             | Bump **part_generation**, then set all participants **live_status** to **busy.**                                                                                                                                                                                                                                                        |
| Lesson content          | Lessons are synced from a **required per-lesson YAML manifest** (manifest is source of truth for part order). On live-session drift, instructor gets a prompt (default selection: **Switch to latest**). Invalid/missing manifest is a hard sync failure and sets repo unhealthy.                                                       |
| Part while paused       | **Frozen** — reject instructor **part_changed** (HTTP **422/409**); disable Prev/Next in UI.                                                                                                                                                                                                                                            |
| Multi-instructor model  | Session uses **SessionInstructor** assignments (one primary optional + zero-or-more co-instructors). At least one active instructor required while status is not ended. Removing/replacing instructors is **blocked (409)** if operation would leave zero active instructors.                                                           |
| Member role exclusivity | A user may be assigned as **either instructor or trainee** per session — never both simultaneously. If role is changed, remove the conflicting assignment in the same transaction.                                                                                                                                                      |
| Repo / entitlement loss | Active sessions keep reading **cached LessonPart** until **ended**; **LessonRepo.health = unhealthy** + banner; block **new** sessions on that repo.                                                                                                                                                                                    |
| Account delete          | **Anonymize** workshop rows: null **user_id**, set **anonymization_ref**, **anonymized_at**; add **UNIQUE (session_id, anonymization_ref)** (or equivalent) because **UNIQUE (session_id, user_id)** is degenerate with multiple NULLs — see Privacy section.                                                                           |
| Trainee peer visibility | **Trainees never see other participants’ identity, busy/done, joined_at, finished_at**, or roster. **Lesson content + session state badge + own controls only.** Enforce in **API response shape** and **WebSocket fanout**, not merely hidden UI.                                                                                      |
| Avatar scope across app | Use GitHub profile image on **all identity surfaces** (sidebar/user menu, settings/profile, admin user tables, instructor rosters, session cards) when linked. Fallback to initials/generic avatar when missing. **Trainee-facing session payloads still omit peers**; trainees may see **only their own** avatar in personal contexts. |
| WS handshake            | WebSocket auth uses **Sec-WebSocket-Protocol** carrying ws-ticket (no first-message auth mode).                                                                                                                                                                                                                                         |
| Member role conflict    | Add-member role conflicts are resolved by **always replace** semantics atomically (no manual conflict endpoint required).                                                                                                                                                                                                               |
| OAuth/App setup         | **Separate OAuth App (login)** + **separate GitHub App (repo sync)** for MVP.                                                                                                                                                                                                                                                           |
| Entitlement scope       | **Instructor-bound** by default; instructors can invite other instructors explicitly.                                                                                                                                                                                                                                                   |
| Realtime scaling path   | **Stay single-process** hub in PR04; defer Redis/multi-process fan-out until measured scale/concurrency requires it.                                                                                                                                                                                                                   |
| Avatar refresh          | Refresh stored avatar_url on each successful GitHub sign-in/link event (no periodic background refresh).                                                                                                                                                                                                                                |
| Avatar unlink           | On GitHub unlink, clear stored avatar_url and fall back to initials/default avatar.                                                                                                                                                                                                                                                     |
| API contract gate       | OpenAPI + TS client regeneration is **required on every API contract change**.                                                                                                                                                                                                                                                          |
| CI branch gate          | Critical workflows (backend tests, docker-compose tests, Playwright, staging deploy checks) must run on default branch **main** and PRs; no `master`-only gaps.                                                                                                                                                                         |
| Webhook replay safety   | Webhook processing requires signature verification + replay-window checks + delivery idempotency before side effects.                                                                                                                                                                                                                   |
| Endpoint throttling     | Apply route-level throttling for auth bridge, login, and webhook endpoints.                                                                                                                                                                                                                                                             |


## Template code anchors


| Layer         | Paths                                                                                                                                                                                                     |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend       | [backend/app/models.py](backend/app/models.py), extend API next to [backend/app/api/routes/oauth.py](backend/app/api/routes/oauth.py)                                                                     |
| Frontend      | Replace/supplant [frontend/src/routes/_layout/items.tsx](frontend/src/routes/_layout/items.tsx); sidebar [frontend/src/components/Sidebar/AppSidebar.tsx](frontend/src/components/Sidebar/AppSidebar.tsx) |
| Auth.js       | [authjs-service/auth.ts](authjs-service/auth.ts), [authjs-service/app/api/bridge/route.ts](authjs-service/app/api/bridge/route.ts) (login path unchanged)                                                 |
| Bridge crypto | [backend/app/core/security.py](backend/app/core/security.py)                                                                                                                                              |


## GitHub App

- Env: **GITHUB_APP_ID**, **GITHUB_PRIVATE_KEY** (PEM), **GITHUB_WEBHOOK_SECRET**, public HTTPS webhook URL.
- **Webhooks**: Verify **X-Hub-Signature-256**; rate-limit the endpoint; optionally dedupe using **X-GitHub-Delivery** when present.
- **Entitlement MVP**: **instructor-bound** repository access by default; repos must be tied to an installation the assigning instructor controls. Other instructors may be explicitly invited to a session.
- **OAuth registration (locked)**: Use **separate OAuth App** for login + **separate GitHub App** for repository sync in MVP.
- **Lesson structure contract (locked)**: each lesson folder must include a YAML manifest (for example `lesson.manifest.yaml`) that explicitly defines lesson parts and ordering; no implicit filename ordering in MVP.
- **Manifest failure policy (locked)**: missing/invalid manifest blocks sync updates and marks `LessonRepo.health=unhealthy` (hard fail, no partial sync).

## Lesson manifest format (locked)

Each lesson folder must contain `lesson.manifest.yaml`.

### Required schema

- `version` (integer): manifest schema version; MVP requires `1`.
- `lesson` (object):
  - `slug` (string, kebab-case, unique per repo)
  - `title` (string)
- `parts` (array, min 1):
  - `slug` (string, kebab-case, unique within lesson)
  - `title` (string)
  - `path` (string, relative markdown file path inside the lesson folder, e.g. `01-intro.md`)

### Optional fields

- `lesson.summary` (string)
- `part.estimated_minutes` (integer >= 0)
- `part.objectives` (array of strings)

### Validation rules

- Manifest file must parse as valid YAML.
- Unknown keys are rejected at **all levels** in MVP (top-level, `lesson.`*, and each `parts[*].`*).
- Every `parts[*].path` must exist and be a markdown file (`.md` only in MVP).
- Part order is exactly the array order in `parts`; no filename sorting fallback.
- Duplicate `lesson.slug` in the same repo or duplicate `parts[*].slug` in the same lesson is invalid.
- Path safety is enforced: reject absolute paths, reject any `..` traversal, and reject symlink-resolved targets that escape the lesson folder root.
- Any validation error causes hard sync failure for that repo update and sets repo health to unhealthy.

### Example

```yaml
version: 1
lesson:
  slug: fastapi-workshop-basics
  title: FastAPI Workshop Basics
  summary: Intro workshop for API fundamentals.
parts:
  - slug: setup-and-prereqs
    title: Setup and Prerequisites
    path: 01-setup.md
    estimated_minutes: 10
    objectives:
      - Install dependencies
      - Run the project locally
  - slug: first-endpoint
    title: Build Your First Endpoint
    path: 02-first-endpoint.md
    estimated_minutes: 20
```

### JSON Schema (draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/lesson-manifest.schema.json",
  "title": "LessonManifestV1",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "lesson", "parts"],
  "properties": {
    "version": {
      "type": "integer",
      "const": 1
    },
    "lesson": {
      "type": "object",
      "additionalProperties": false,
      "required": ["slug", "title"],
      "properties": {
        "slug": {
          "type": "string",
          "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
          "minLength": 1
        },
        "title": {
          "type": "string",
          "minLength": 1
        },
        "summary": {
          "type": "string"
        }
      }
    },
    "parts": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["slug", "title", "path"],
        "properties": {
          "slug": {
            "type": "string",
            "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
            "minLength": 1
          },
          "title": {
            "type": "string",
            "minLength": 1
          },
          "path": {
            "type": "string",
            "pattern": "^(?!/)(?!.*\\.\\.)(?!.*\\\\).+\\.md$"
          },
          "estimated_minutes": {
            "type": "integer",
            "minimum": 0
          },
          "objectives": {
            "type": "array",
            "items": {
              "type": "string",
              "minLength": 1
            }
          }
        }
      }
    }
  }
}
```

Implementation note: JSON Schema cannot reliably validate symlink-escape checks; enforce symlink root containment in backend filesystem validation after schema validation.

## Session lifecycle

```mermaid
stateDiagram-v2
  [*] --> scheduled
  scheduled --> live: goLive
  live --> paused: pause
  paused --> live: resume
  live --> ended: endSession
  paused --> ended: endSession
```



- **Scheduled**: **POST /enter** rejected. Optional backlog: read-only lesson title on lobby (no joined_at).
- **Live / paused**: **enter** allowed; **paused** blocks participant **live_status** updates and blocks **part_changed**.

## Flow diagrams

### Post-login dashboard routing

```mermaid
flowchart TD
  loginSuccess[LoginSuccess] --> isInstructor{isInstructor}
  isInstructor -->|yes| instructorHome[InstructorHome]
  isInstructor -->|no| isSuperuser{isSuperuser}
  isSuperuser -->|yes| adminHome[AdminHome]
  isSuperuser -->|no| traineeHome[MyLearningHome]
  instructorHome --> quickSwitch[OptionalQuickSwitchToAdmin]
```



### GitHub App sync flow

```mermaid
flowchart TD
  instructorAction[InstructorAddsOrSyncsRepo] --> validateRole[CheckInstructorAuthorization]
  validateRole --> fetchInstallation[ResolveGithubInstallation]
  fetchInstallation --> mintToken[MintInstallationToken]
  mintToken --> fetchTree[FetchLessonFoldersAndYamlManifests]
  fetchTree --> validateManifest[ValidatePerLessonYamlManifest]
  validateManifest -->|valid| fetchParts[FetchManifestReferencedMarkdownParts]
  validateManifest -->|invalidOrMissing| markUnhealthy[SetLessonRepoHealthUnhealthy]
  fetchParts --> upsertLessonRepo[UpsertLessonRepo]
  upsertLessonRepo --> upsertLesson[UpsertLesson]
  upsertLesson --> upsertParts[UpsertLessonPartsBySlugAndOrder]
  upsertParts --> bumpGeneration[BumpLessonSyncGeneration]
  bumpGeneration --> markHealthy[SetLessonRepoHealthHealthy]
  fetchParts --> rewriteAssets[RewriteRelativeAssetsToGithubRaw]
  rewriteAssets --> upsertLessonRepo
```



### Live session event/privacy flow

```mermaid
flowchart TD
  sessionOpen[UserOpensSession] --> enterApi[POSTEnter]
  enterApi --> wsTicket[POSTWsTicket]
  wsTicket --> wsConnect[WSConnectSecWebSocketProtocol]
  wsConnect --> roleBranch{ConnectionRole}
  roleBranch -->|instructor| fullFanout[FullRosterAndLiveStatusFanout]
  roleBranch -->|trainee| scopedFanout[ScopedFanoutPartAndSessionAndSelfAck]
  instructorPartChange[InstructorPartChange] --> partGen[IncrementPartGeneration]
  partGen --> resetBusy[ResetAllLiveStatusToBusy]
  resetBusy --> fullFanout
  resetBusy --> scopedFanout
```



### Badge grant/revoke lifecycle

```mermaid
flowchart TD
  traineeFinish[TraineeMarksFinished] --> pendingVerify[CompletionPendingInstructorVerification]
  pendingVerify --> instructorVerify[InstructorVerifiesCompletionSingleOrBulk]
  instructorVerify --> grantBadge[GrantUserBadge]
  grantBadge --> showSurfaces[ShowOnProfileSessionLeaderboard]
  showSurfaces --> revokeDecision{RevokeNeeded}
  revokeDecision -->|yes| revokeReason[InstructorProvidesMandatoryReason]
  revokeReason --> revokeBadge[RevokeBadgeAndWriteAuditTrail]
  revokeBadge --> updateViews[RemoveFromActiveCountsAndLeaderboard]
  revokeDecision -->|no| keepBadge[BadgeRemainsActive]
```



## Data model (illustrative)


| Entity                                      | Notes                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GithubInstallation (+ optional repo mirror) | Tracks installations and entitled **owner/repo** list.                                                                                                                                                                                                                                                                           |
| LessonRepo                                  | installation_id, full_name, default_branch, sync timestamps, **health** (healthy                                                                                                                                                                                                                                                 |
| Lesson                                      | FK to LessonRepo; optional **lesson_sync_generation** after sync.                                                                                                                                                                                                                                                                |
| LessonPart                                  | lesson_id, ordering, path, **slug** (unique per lesson), title, body_md.                                                                                                                                                                                                                                                         |
| LessonManifest                              | lesson_id, manifest_path, manifest_sha, manifest_format=yaml, parsed_at, validity_state, error_message (nullable).                                                                                                                                                                                                               |
| WorkshopSession                             | lesson_id, status, current_part_index, current_part_slug, **part_generation**, timestamps. (Primary instructor id optional convenience pointer if desired.)                                                                                                                                                                      |
| WorkshopParticipant                         | session_id, user_id (nullable after anonymize); invited_at, joined_at, finished_at, live_status, removed_at; anonymization_ref, anonymized_at; instructor audit columns (adjusted_*, reason).                                                                                                                                    |
| SessionInstructor                           | session_id, user_id (must be **is_instructor=true**), role enum (primary/co_instructor optional), assigned_at, removed_at; unique active (session_id,user_id).                                                                                                                                                                   |
| InstructorNote                              | scope (lesson/session), scope_id, author_user_id, note_md/text, created_at, updated_at; instructor/superuser visible only.                                                                                                                                                                                                       |
| LessonPrerequisite                          | lesson_id, type (task/link/check), title, details/url, ordering, required_flag.                                                                                                                                                                                                                                                  |
| UserPrerequisiteCompletion                  | user_id, lesson_id, prerequisite_id, completed_at, source (self/instructor).                                                                                                                                                                                                                                                     |
| Cohort                                      | name, slug, description, owner_instructor_id, archived_at.                                                                                                                                                                                                                                                                       |
| CohortMembership                            | cohort_id, user_id, role (member/lead optional), added_at, removed_at.                                                                                                                                                                                                                                                           |
| SessionCohortAssignment                     | session_id, cohort_id (optional for cohort-targeted sessions and filtering).                                                                                                                                                                                                                                                     |
| SessionReminder                             | session_id, reminder_type (start_24h/start_1h/pause/resume/custom), scheduled_for, sent_at, channel=in_app.                                                                                                                                                                                                                      |
| SessionTimerEvent                           | session_id, part_slug/index, timer_mode (countdown/countup), started_at, paused_at, ended_at, target_seconds.                                                                                                                                                                                                                    |
| SessionFeedbackPrompt                       | lesson_id or session_template_id, question_text, question_type (rating/text/multi), required_flag, ordering.                                                                                                                                                                                                                     |
| SessionFeedbackResponse                     | session_id, user_id, prompt_id, response_value/text, submitted_at (trainee-visible only to self; instructor sees aggregate and authorized drill-down).                                                                                                                                                                           |
| User (extend template)                      | Nullable `**avatar_url`** (or `**github_avatar_url`**) — set/updated when GitHub is linked (from GitHub profile `**avatar_url`** at link/approval or periodic refresh on successful GitHub sign-in). Join instructor roster DTO with `**full_name**`, `**email**` (optional policy), `**github_login**` from `**OAuthAccount**`. |
| OAuthAccount (template)                     | Already links **GitHub**; ensure `**avatar_url`** is captured if not present today (may require extending model + bridge payload from Auth.js **profile.image** at link time).                                                                                                                                                   |


**Roster read model (instructor):** `ParticipantRosterRow` = participant session fields + `**avatar_url`**, `**display_name`**, `**github_login**` (nullable). **Anonymized** rows: omit photo or use neutral placeholder.

**Sync**: Single-flight (advisory lock or row lock) around manifest validation + fetch + upsert of **LessonPart**; bump generation so clients can warn on mid-session content change.

## Realtime

- **ws-ticket**: **POST …/ws-ticket** returns a **short-lived** token; do **not** put long-lived JWT in query strings. Use **Sec-WebSocket-Protocol** (locked); first-message auth mode is out of scope.
- **Role-scoped fanout (privacy)**:
  - **Instructor-assigned users (and superuser observers if any)** connection: server may push **full roster snapshots** / per-participant **live_status** deltas for UI cockpit (snapshots may include avatar_url per row — instructor-only channel).
  - **Trainee** connection: payloads **restricted to** session-level `**part_changed`** (slug/index/generation/markdown-or-ref), `**session_status`** (live/paused/ended), and **ack/echo only for their own user_id** (e.g. their **live_status** confirm). **Never** embed other participants’ IDs, names, or statuses. If a single WS room is reused, enforce filter at broadcast; preferable **two channels** (`role=instructor|trainee`) with different message schemas typed in OpenAPI/TS.
- **part_generation**: Increment **before** broadcasting **part_changed** to **all** subscribed clients (**trainees need part sync without peer data**). Trainees send last-known generation + **self-only live_status** updates when live.
- **Pause matrix**: Trainee writers for **live_status** off; instructor **part_changed** off; roster PATCH and progress audit PATCH still allowed; resume/end allowed.

## Persistence rules


| Field                                 | Writer                                                                     |
| ------------------------------------- | -------------------------------------------------------------------------- |
| joined_at                             | First successful **POST …/enter** only.                                    |
| live_status, finished_at (self-serve) | Only when session is **live**, not **paused** (WS or REST per API design). |
| Instructor overrides                  | **PATCH** participant with audit columns.                                  |


## REST sketch (under /api/v1/…)


| Verb   | Route                                           | Notes                                                                                                                                                                                         |
| ------ | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | …/workshop/sessions/{id}/enter                  | Idempotent joined_at; **403** if scheduled.                                                                                                                                                   |
| POST   | …/workshop/sessions/{id}/ws-ticket              | Ephemeral WS credential.                                                                                                                                                                      |
| POST   | …/workshop/sessions/{id}/members                | Add member with role selection: trainee OR instructor (mutually exclusive). Instructor role requires is_instructor.                                                                           |
| PATCH  | …/workshop/sessions/{id}                        | State transitions; instructor assignment updates (primary/co-instructor) with is_instructor checks. **409** if change leaves no active instructor on non-ended session.                       |
| DELETE | …/workshop/sessions/{id}/participants/{user_id} | Soft **removed_at**.                                                                                                                                                                          |
| PATCH  | …/workshop/sessions/{id}/participants/{user_id} | Instructor audit overrides.                                                                                                                                                                   |
| GET    | …/workshop/sessions/{id} (and related)          | Trainee-visible fields: **scoped DTO** — no roster array; no peer stats. Instructor GET returns full roster + aggregates **including `avatar_url` (and display fields) per participant row**. |


Routes are illustrative; align names with your OpenAPI layout. **Separate response models** (`SessionPublicParticipant` vs `SessionPublicInstructor`) recommended.

Additional endpoint groups to include:

- `GET/POST/PATCH /workshop/sessions/{id}/notes` (private instructor notes)
- `GET/POST/PATCH /workshop/lessons/{id}/prerequisites` and `POST /workshop/lessons/{id}/prerequisites/{pid}/complete`
- `GET/POST/PATCH /workshop/cohorts` + membership endpoints; optional `POST /workshop/sessions/{id}/cohorts/{cohort_id}`
- `POST /workshop/sessions/{id}/reminders/schedule` + worker-driven send/status endpoints
- `POST /workshop/sessions/{id}/timer/start|pause|resume|stop` + `GET /workshop/sessions/{id}/timer`
- `GET /workshop/sessions/{id}/feedback/prompts` + `POST /workshop/sessions/{id}/feedback/responses` + instructor aggregate read endpoint
- `GET /workshop/attendance/exports` + `POST /workshop/attendance/exports` (CSV generation, scoped filters)

Role guardrail (consistent with Locked decisions): add-member endpoint applies **always replace** semantics for opposite-role conflicts in a single transaction; dual-role state is forbidden.

Last-instructor guardrail: for sessions with status != ended, instructor remove/demote/handoff requests that would result in **zero active SessionInstructor rows** return **409** with remediation hint (assign another instructor first).

**Avatar loading:** Prefer **HTTPS `avatars.githubusercontent.com`** URLs stored at link/sign-in refresh time. Apply same avatar source helper across all identity UIs (sidebar profile button, settings/profile header, admin users table, instructor roster rows, session cards). Optional hardening: proxy images through FastAPI (cache + strip cookies) if CSP/privacy requires; MVP may use `referrerPolicy="no-referrer"` and framework remote host allowlist for GitHub avatar domains.

## Markdown

Render GFM → HTML through a **sanitize** allowlist (**bleach**, **nh3**, or equivalent) before the SPA.
Rewrite relative markdown asset links/images to `raw.githubusercontent.com` URLs at sync/read-model build time for stable rendering.

## Notifications (MVP)

- Notification model is **in-app only** (no email for MVP).
- Delivery surfaces: **toast + notification center**.
- Initial events: added-to-session, session-started, session-paused/resumed, badge-granted, badge-revoked.

## Migration and rollout safety

- **Pre-migration checks:** capture baseline row counts, confirm backup availability, and document rollback posture for each migration.
- **Post-migration checks:** verify constraints/indexes, run integrity checks, and validate seed reads for repos/lessons/sessions.
- **Backfill requirement:** any new non-null/derived field must include a backfill query/job plus a verification query.
- **Destructive change policy:** table/column drops require deprecation staging unless explicitly approved as emergency work.

## API and operational discipline

- **Error envelope:** new workshop endpoints should return a machine-readable error shape (`code`, `message`, optional `details`).
- **Idempotency contracts:** explicitly define idempotency behavior for `enter`, webhook sync handlers, and badge grant/revoke actions.
- **Observability minimum:** add structured logs with request/session IDs and metrics for sync failures, ws connect failures, and badge/revocation actions.
- **Alertability:** define thresholds for repeated webhook verification failures and sustained `LessonRepo.health=unhealthy`.

## Security hardening for added workshop features

- **Field-level RBAC:** enforce instructor/superuser-only access for instructor notes, cohort management, attendance export endpoints, reminder controls, timer controls, and feedback aggregate drill-down endpoints.
- **Scoped data exposure:** trainees can read only their own prerequisite completions and feedback responses; never return peer identity/response payloads in trainee DTOs.
- **CSV injection defenses:** sanitize export cells that begin with spreadsheet formula prefixes (`=`, `+`, `-`, `@`) and emit safe quoted CSV.
- **Export minimization:** default attendance export mode includes only necessary columns; extended PII columns require explicit privileged flag.
- **Reminder anti-abuse controls:** enforce per-session/per-instructor cooldown, deduplication keys, and max reminders per time window.
- **Timer integrity:** timer state is server-authoritative; reject client-supplied backdated timestamps and enforce legal state transitions.
- **Notes and timer auditing:** immutable audit trail for note create/edit/delete and timer start/pause/resume/stop with actor and timestamp.
- **Feedback privacy threshold:** only show cohort/segment feedback aggregates when minimum respondent threshold is met.
- **Background job integrity:** reminder/export workers must use idempotency keys and trusted queue payloads (no unauthenticated trigger path).
- **Retention and deletion policy:** define retention windows and deletion/anonymization behavior for notes, feedback text, reminder logs, and export artifacts.

## Privacy (user delete)

**Anonymize** linked **WorkshopParticipant** rows (null **user_id**, stable **anonymization_ref** per row, timestamp). Document in privacy copy. Ensure DB constraints allow one anonymized row per original seat (partial unique indexes as needed). Clean up Auth.js linkage per your account-deletion policy.

## Post-login landing dashboards

This section defines exactly where users land **immediately after login**.

### Landing rules (locked)

- **Instructor (`is_instructor=true`)**: land on **Instructor Home** (`/dashboard/instructor`).
- **Trainee-only user**: land on **My Learning Home** (`/dashboard/trainee`).
- **Superuser**:
  - If also instructor, default to **Instructor Home** with quick-switch to admin view.
  - If not instructor, land on **Admin Home** (`/dashboard/admin`) with links to workshop/instructor management.

Persist user's last dashboard tab (optional quality-of-life), but first-login defaults follow the rules above.

### Dashboard pages to include


| Dashboard            | Audience    | Purpose                                                                                                                                                           |
| -------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Instructor Home**  | instructors | Today's sessions, active/paused sessions, repo health, pending completion verifications, badge/revocation actions, quick links to lesson repos/sessions/analytics |
| **My Learning Home** | trainees    | sessions needing action (live/starting soon), recent completions, earned badges, personal progress summary                                                        |
| **Admin Home**       | superusers  | user/instructor management, system health summaries, policy/role oversight, links into workshop data                                                              |


### Minimal cards for each landing dashboard

- **Instructor Home cards**
  - Live now / paused now sessions
  - Sessions starting today
  - Pending completion verifications
  - Repo health warnings (unhealthy LessonRepo)
  - Badge actions queue (recent grants/revokes)
- **My Learning Home cards**
  - Continue session (if any live/paused where user is trainee)
  - Upcoming sessions where rostered
  - My badges (recently earned)
  - Personal completion trend (no peer metrics)
- **Admin Home cards**
  - Users pending role changes
  - Instructors and active sessions summary
  - Error/warning rollup (sync failures, unhealthy repos)

### Privacy constraints on landing dashboards

- Trainee dashboard must never include peer trainee identities, statuses, counts tied to named peers, or instructor-only roster controls.
- Instructor dashboard may include roster summaries for sessions they are assigned to.
- Admin dashboard may include aggregates and management views according to superuser permissions.

## Dashboard content matrix

The app should present role-specific dashboard content that matches all features in this plan.


| Surface                      | Instructor dashboard                                                                                                                                                            | Trainee dashboard                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Primary nav**              | Instructor Home, Workshops hub, Lesson repos, Sessions, Analytics, Badge management/revocations; includes trainee routes only when instructor is separately rostered as trainee | My Learning Home, My sessions, My badges/profile progress (plus standard account settings)    |
| **Session list cards/table** | lesson, status, invited/joined/finished counts, health warnings, open/manage actions                                                                                            | only sessions where user is participant/instructor, personal status; no peer metrics          |
| **Session detail**           | full roster, avatars, busy/done per trainee, joined/finished timestamps, verify completion, revoke badge, pause/resume/end, member role assignment                              | current lesson part, own busy/done + own completion action, status badge; no roster/peer data |
| **Badges**                   | badge grant/revoke actions, per-session badge events, leaderboard moderation context                                                                                            | own earned badges + progress only                                                             |
| **Analytics**                | attendance/completion analytics (session + cross-session trends)                                                                                                                | none (trainee gets personal progress only, no cohort analytics)                               |
| **Error/health banners**     | sync failures, unhealthy LessonRepo, entitlement issues                                                                                                                         | session-level read-only/error guidance only; no admin internals                               |


### Dashboard consistency rules

- **Role-gated widgets:** every widget/card/query in dashboards must check role scope server-side and client-side.
- **Single source DTOs:** use separate API response models for instructor and trainee dashboards; never reuse instructor DTOs in trainee routes.
- **Feature propagation checklist:** whenever a new domain feature is added (badges, revocation, analytics, role rules), update both dashboards intentionally: either add relevant widget or explicitly mark "not applicable".
- **No silent gaps:** dashboard pages should not expose empty placeholders for unsupported role actions; hide or replace with contextual copy.

## UI / UX specification

**Layout choices (locked):**

- **Instructor live cockpit (desktop / large tablet): split panel** — roster + presence on one rail; current **LessonPart** Markdown + **Prev / Next** + session controls on the main pane. On narrow viewports, **stack**: roster summary strip (horizontally scroll chips or collapsible drawer) above the lesson card.
- **Participant: full app chrome** — keep the **normal sidebar and global nav** (per template) so trainees can move to settings or other routes; no forced “focus mode” kiosk. Session page still shows **clear session state** (badge: Scheduled / Live / Paused / Ended) so context is obvious when they return.

### Global avatar usage (locked)

- **Apply avatar component consistently** wherever a user identity chip appears: app sidebar/profile trigger, account/settings header, admin user rows, instructor session roster, and workshop/session list cards.
- Source priority: **GitHub avatar URL** (if linked) → user-uploaded avatar (future, if added) → initials placeholder.
- **Participant privacy guard** remains unchanged: on trainee session pages, show only the current user's avatar where relevant; never render peer avatar collections/rows.

---

### Information architecture (sidebar / nav)

Suggested top-level entries (names illustrative; wire to `is_instructor`):


| Route (illustrative)                             | Who         | Purpose                                                                                                                                               |
| ------------------------------------------------ | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Instructor Home**                              | Instructor  | Default post-login landing for instructors; cards + quick actions.                                                                                    |
| **Workshops** (or **Lessons**)                   | Instructor  | Hub: links to **Repos** + **Sessions** or sub-routes.                                                                                                 |
| **Lesson repos**                                 | Instructor  | List **LessonRepo**, “Install GitHub App” CTA, **Sync**, health badge, link to preview **parts** list. CTA rendered only for instructor-scoped pages. |
| **Sessions**                                     | Instructor  | Table: title/lesson, status, start time, row → **session detail**.                                                                                    |
| **My Learning Home**                             | Participant | Default post-login landing for trainees; cards for active/upcoming sessions and badges.                                                               |
| **My sessions** (or under generic **Workshops**) | Participant | Rows for sessions they’re **on the roster** for; deep link **Open** → `/sessions/:id`.                                                                |
| **Session live**                                 | Both        | `/sessions/:id` — role renders different panels (below).                                                                                              |
| **Admin Home**                                   | Superuser   | Default post-login landing for non-instructor superusers; user/role/workshop oversight cards.                                                         |


Trainees without instructor flag land on **My Learning Home** and see trainee entries only (+ standard account routes). Instructors land on **Instructor Home** and see instructor entries when assigned as session instructors; they can also appear in trainee pages when enrolled as trainees.

---

### Instructor — key screens

**1) Lesson repos**

- Page title + short copy: “Repo must be granted to the GitHub App.” Primary **Install / configure app** (external). This CTA appears only for instructor-authorized views.
- Table: **repo full name**, last sync time, **health** pill, **Actions**: Sync, View parts (modal or sub-page), optional remove (with confirm if no active sessions).
- **Empty state**: illustration + CTA to add first repo (`owner/repo` field + validation against entitlement API).

**2) Sessions list**

- Filters: status, date, lesson title search.
- Additional filters: cohort/team, prerequisite completion state, reminder state.
- Columns: Lesson name, Status (color chip), Participant count invited / joined, **Open**.

**3) Session detail — scheduled (lobby)**

- Header: lesson title, status **Scheduled**, **Go live** primary button.
- **Members** card: searchable user picker with role selector. If picked user has **is_instructor=true**, selector allows trainee OR instructor (mutually exclusive); otherwise trainee only. Table shows role badges, avatar, invited/assigned times, remove (soft).
- Secondary: **Handoff** (combobox: only **is_instructor** users) — available before or after go-live.
- Optional backlog: read-only **Lesson title** / first part preview (no **enter** until live).

**4) Session detail — live / paused (cockpit)**

- **Top bar (full width):** Session status chip (**Live** green / **Paused** amber / **Ended** gray), **Pause** / **Resume** / **End session** (destructive confirm for End). If **LessonRepo** unhealthy: **inline banner** (“Source unavailable — showing last synced content”) non-blocking.
- **Top bar tools:** session timer widget (countdown/count-up, part target, overrun indicator) and reminder controls (send now / schedule in-app reminder).
- **Content drift handling:** if sync changes active lesson structure while session is live, show instructor prompt with choices **Switch to latest** (default preselected) or **Keep current snapshot** for this session.
- **Split panel:**
  - **Left rail (≈30–40% min-width 280px):** “Roster” table — **Avatar** (32–40px circle, **GitHub profile image** or **fallback initials**), Name / **GitHub @handle** (optional subline), **Status** pill (**busy** red / **done** green), **Joined** / **Finished** times. Sort by name or status. Row actions: **Adjust…** (opens sheet: edit timestamps + reason for audit). **Add participant** / remove if session not ended.
  - **Right main:** **Current part** title (H2) + **Part N of M** + **Prev** / **Next** (disabled when **paused** or **ended**; disabled **Next** on last part). Below: **rendered Markdown** in a scrollable card (prose width max ~65ch for readability).
- **Pause:** show subtle **“Paused — participant updates frozen”** subtext; Prev/Next visibly disabled; roster still readable; instructor can still edit roster / audits / handoff per API rules.
- **Private notes panel:** instructor-only notes drawer for session observations, blockers, and follow-up actions.

**5) Session detail — ended**

- Read-only roster + final timestamps; **no** pace controls. Option: **Duplicate session** (backlog) for another cohort.

---

### Participant (trainee) — key screens

**Privacy rule:** No UI that reveals **who else is in the room**, **how far along others are**, or **busy/done for anyone but self** in session pages.

**Badges/awards:** Badges are shown on profile, My Sessions, and dedicated leaderboard surfaces (cross-session context).

**1) My sessions**

- List: session/lesson title, **my** status badge (scheduled/live/paused/ended — session-level only), prerequisite completion badge, **Open**. **Do not show** invitee totals or peer progress.

**2) Session page `/sessions/:id`**

- **Header:** lesson title + **session** status badge + instructor attribution if allowed (single name/string — **not** a participant list). Show the trainee's own avatar in personal header/menu contexts only.
- **Scheduled:** “Session hasn’t started” + **no Enter**.
- **Prework card:** prerequisite checklist with completion actions/status before session starts.
- **Live:** **Enter** (sets **joined_at**); then **lesson Markdown** + **your** **Busy/Done** (red/green for **your** row only—instructor UI aligns colors; trainee only ever sees **their** state). Secondary: **I’m finished with this lesson** (**finished_at**, confirm dialog). **No roster rail, leaderboard, or avatar stack.**
- **Paused:** banner; toggles disabled; content frozen.
- **Ended:** closed state; optional last part read-only; no toggles.
- **Reconnect:** toast + resilient **ws-ticket** refresh.
- **End-of-session feedback:** after session end (or explicit instructor trigger), show reflection form (rating + free text as configured prompts).

Accessibility: unchanged for **personal** toggles + **aria-live** for **your** view when instructor advances parts (announcement text like “Moved to Part 3” — **no** peer names).

### Instructor analytics screens

- **Session analytics tab (instructor-only):**
  - KPIs: invited, joined, finished, completion %
  - Join delay distribution (e.g., median + p90)
  - Time-to-finish distribution for verified completions
  - Pause/resume count + total paused duration
  - Badge grant/revocation summary for that session
  - Cohort/team comparison slices and prerequisite completion correlation
  - Feedback summary (ratings distribution + tagged themes)
- **Cross-session analytics page (instructor-only):** trends over time by lesson/session and cohort-level completion.
- **Visibility scope lock:** instructors see analytics only for sessions they own/are rostered on; no org-wide instructor visibility into unrelated sessions.

### Badge revocation workflow

- In instructor session detail and badge management views, each badge grant row can be revoked.
- Revocation requires **reason** (mandatory), captures actor/timestamp, and optionally learner-visible note.
- Revoked badges disappear from active counts/leaderboard and are shown as revoked in audit/history views.

### Awards / leaderboard screens

- **Profile/settings:** badge collection grid (earned/unearned optional), grant timestamps, and associated lesson/session context when available.
- **My Sessions:** compact badge chips on completed session cards.
- **Instructor session detail:** verified-completion action includes visible badge grant confirmation per trainee.
- **Global leaderboard page:** rank by total score from **per-badge custom points** (active, non-revoked grants only); clearly separate from live session UI.
- **Badge catalog ownership:** instructors can manage badges only for lessons/repos they control; superusers have global override.

### Cohorts / teams and exports

- Instructor cohort management screen: create/archive cohorts, add/remove members, assign cohorts to sessions.
- Session roster supports cohort filter and team-level pacing view (instructor-only).
- Attendance export supports CSV columns for cohort, joined_at, finished_at, join_delay, verification/badge status, and prerequisite completion.

### Visual / design system notes

- Reuse existing template **Card**, **Badge**, **Button**, **Sheet/Dialog**, **Sidebar** patterns from `[frontend/src/components/ui](frontend/src/components/ui)` for consistency dark/light.
- **Status colors — instructor roster:** busy → red-toned pill; done → green-toned pill (**per trainee row**).
- **Status colors — trainee self:** same red/green language for **only their** Busy/Done control (not labelled as copying “the roster column”).
- **No chat UI** anywhere (no empty message panels).

---

### Empty, error, and permission states

- **403** roster not invited: friendly “Ask your instructor to add you.”
- **Enter** rejected (scheduled): “Session not started yet.”
- **Repo sync failed**: instructor sees error on repo row + retry **Sync**.
- Loading skeletons on session open while fetching session + WS ticket.

---

### Time & copy

- Display times in **user locale**; store **UTC** (already planned).
- Microcopy uses “Workshop” / “Session” / “Lesson part” consistently in UI strings.

---

### Post-MVP UI (references only)

- XLSX/PDF export templates and scheduled report delivery.
- Optional **focus mode** for participants (if feedback says full chrome is distracting) — **not** in MVP given your choice above.

## Testing

- Unit: webhook bad signature; enter when scheduled; stale **part_generation** mutation; sync idempotency; handoff **422** when target not instructor; **last-instructor removal blocked (409)** on non-ended sessions; add-member opposite-role invokes always-replace atomically; badge grant only on instructor verification; badge revocation requires reason.
- Unit: manifest missing/invalid hard-fails sync + marks repo unhealthy; relative asset rewrite to raw GitHub URLs; avatar cleared on unlink; bulk verify can grant for arbitrary selected trainees (no finished-only guardrail).
- Playwright: two trainee profiles **cannot** observe each other's status or avatars in session views; instructor sees both; trainee GET/WS payloads snapshot-tested for absence of peer PII/live_status/avatar fields; badge appears only after instructor verify action; revocation removes badge from learner surfaces + leaderboard.
- Playwright: in-app notifications appear as toast and in notification center for roster/session/badge events; live content drift prompt appears to instructor with default preselection **Switch to latest**.
- Analytics API/UI tests: instructor can view analytics pages; trainee receives 403; metrics reflect join/finish/pause events accurately.
- Dashboard role-scope tests: trainee dashboard never renders instructor-only cards (roster, peer stats, revocation controls); instructor dashboard shows all applicable management cards.
- Post-login landing tests: route to correct dashboard by role (`is_instructor`, superuser combinations), including fallback when role changes after login.
- UI consistency checks: avatar helper renders GitHub avatars on sidebar/profile/admin table/instructor roster/session cards with fallback initials when missing.
- Contract checks: OpenAPI + generated TS client updated on every API contract change (CI-enforced).
- CI readiness checks: critical workflows trigger on `main` + PR; fail build on OpenAPI/client drift for changed API surfaces.
- Security checks: webhook replay/idempotency tests and route-throttling tests for auth bridge/login/webhook routes.
- Unit/API: private notes visibility tests (instructor-only), prerequisite completion semantics, cohort membership constraints, reminder scheduling idempotency, timer state transitions, feedback prompt/response validation.
- Playwright: trainee prework checklist flow, instructor timer controls + overrun UI, cohort-filtered roster analytics, attendance CSV export success path, end-of-session reflection submission.
- Security tests: RBAC denial tests for all new endpoint families; CSV formula-injection regression tests; reminder cooldown/max-rate enforcement; feedback privacy-threshold checks for aggregate analytics.

## Risks


| Risk                              | Mitigation                                                                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Content drift during live session | instructor prompt (switch/latest vs keep snapshot) with safe state transition + audit of selected mode                                      |
| JWT in WS URL                     | ws-ticket                                                                                                                                   |
| Peer status leak via API/WS       | Participant DTO + filtered fanout; contract tests                                                                                           |
| XSS from lessons                  | sanitize                                                                                                                                    |
| Webhook abuse                     | signature + throttle                                                                                                                        |
| Webhook replay/duplication        | replay-window validation + delivery idempotency store                                                                                       |
| Sync races                        | single-flight lock                                                                                                                          |
| Multi-instructor consistency      | SessionInstructor unique-active constraints + role exclusivity tests (never dual-role same user/session) + last-active-instructor 409 guard |
| CI blind spots                    | enforce default-branch (`main`) + PR triggers for critical workflows                                                                        |
| Low incident visibility           | structured logs + metrics + alert thresholds for workshop sync/realtime flows                                                               |
| Reminder fatigue/noise            | instructor-configurable reminder presets + cooldown/de-dup rules                                                                            |
| Feedback privacy leakage          | strict scoped DTOs and aggregate thresholds before showing drill-down                                                                       |
| CSV formula injection             | spreadsheet-safe escaping + export sanitization tests                                                                                       |
| Reminder abuse/spam               | rate limits, cooldown windows, and per-session send caps                                                                                    |
| Excessive PII exposure in exports | minimal default export schema + privileged explicit expansion                                                                               |


**Scale**: MVP single-node WS broker; later Redis pub/sub or similar for multi-instance.

## Implementation order

1. **is_instructor** + RBAC (superuser full management APIs; instructor scoped as above), including strict UI/API gating so only instructors see/install GitHub App prompts.
2. GitHub App + webhooks + entitlement + **LessonRepo** + manual sync.
3. Manifest-first lesson sync: per-lesson YAML manifest validation + **Lesson** / **LessonPart** ordering + relative-asset rewriting + sanitized read API.
4. **WorkshopSession** + **SessionInstructor** + **WorkshopParticipant** + state machine + **enter** + exclusive member-role assignment API (no bulk finished_at on end).
5. **ws-ticket** + WS + **part_generation** + pause rules.
6. Instructor + participant UIs; replace **Items** navigation.
7. Integrations: LessonRepo tombstone + handoff negatives.
8. Learning workflow add-ons (**secure-by-default**): prerequisites/prework model + trainee checklist UX + instructor visibility, with scoped DTOs and prerequisite completion authorization checks.
9. Cohorts/teams + attendance exports (**secure-by-default**): cohort CRUD/membership + session assignment + CSV export endpoints/UI with RBAC, export minimization, and CSV formula-injection protections.
10. Session operations add-ons (**secure-by-default**): private instructor notes, reminder automation, and timer/pacing controls with anti-abuse rate limits/cooldowns, server-authoritative timer state, and immutable audit logs.
11. Badge system (**secure-by-default**): catalog ownership rules + per-badge points + single/bulk verify-completion flow + profile/session/leaderboard UI with strict role checks.
12. Analytics + feedback + revocation (**secure-by-default**): session/cross-session analytics, learner reflection summaries, badge revoke endpoint + audit UX with feedback privacy-threshold enforcement.
13. Dashboard parity pass: verify instructor and trainee dashboards include all applicable new modules and exclude non-applicable content by role/privacy.
14. Migration rollout hardening: pre/post migration checks, backfill scripts, and destructive-change guardrails.
15. Final cross-cutting hardening pass: default-branch workflow trigger audit, webhook replay/idempotency checks, throttling coverage validation, monitoring/alert calibration, and threat-model sanity review.
16. Tests + env docs + strict OpenAPI/TS regen verification on each API slice; include dedicated security regression suite and full Playwright E2E coverage for implemented journeys.
17. File post-MVP tickets (focus mode, advanced export templates, optional encryption-at-rest for note/feedback blobs).
18. Ongoing PR operations lane: after each PR open/update in the stack, run `/babysitting-pr` until CI/checks are green or escalation is required for product/design decisions.

Implementation guardrail for steps 1-17: for every backend Python slice, follow `/python-tdd-with-uv` (failing test first, minimal implementation, `uv run pytest` before advancing), and for every user-facing slice ensure corresponding Playwright E2E tests are added/updated before advancing.

## PR slicing and branch strategy (locked)

Use a fully stacked PR chain for implementation delivery.

### Stack model

- Base branch: `main`
- PRs are strictly stacked (`ws-02` targets `ws-01`, `ws-03` targets `ws-02`, and so on).
- Each PR must remain reviewable and testable against its immediate base branch.

### Branch/PR chain

Open GitHub PRs for slices 01–05: see [GitHub PR stack](#github-pr-stack-open--update-when-retargetedmerged). Add the same-style link here when PR06+ exist.

1. `ws-01-foundation-rbac` ([PR #18](https://github.com/justin-p/testing/pull/18) → `main`) — roles, RBAC groundwork, initial schema scaffolding.
2. `ws-02-github-sync-manifest` ([PR #19](https://github.com/justin-p/testing/pull/19) → `ws-01-*`) — GitHub App sync and manifest-first lesson ingestion.
3. `ws-03-session-core` ([PR #20](https://github.com/justin-p/testing/pull/20) → `ws-02-*`) — session lifecycle, rostering, enter semantics, role exclusivity.
4. `ws-04-realtime-privacy` ([PR #21](https://github.com/justin-p/testing/pull/21) → `ws-03-*`) — ws-ticket flow, role-scoped fanout, privacy-safe DTO behavior.
5. `ws-05-dashboard-nav` ([PR #22](https://github.com/justin-p/testing/pull/22) → `ws-04-*`) — post-login routing, instructor/trainee/admin homes, nav replacement.
6. `ws-06-learning-workflows` — prerequisites/prework and learner workflow surfaces. *PR TBD*
7. `ws-07-cohorts-exports` — cohorts/teams model and attendance exports. *PR TBD*
8. `ws-08-notes-reminders-timer` — private notes, reminders, timer/pacing tools. *PR TBD*
9. `ws-09-badges-analytics-feedback` — badges/revocation, analytics, learner feedback. *PR TBD*
10. `ws-10-hardening-and-tests` — cross-cutting hardening, stabilization, and final test consolidation. *PR TBD*

### PR scope guardrails

- Keep changes inside the active slice; avoid cross-slice drift unless required by dependency.
- Apply security-by-default inside each feature PR (do not defer core controls).
- Update OpenAPI/TS client only in PRs that change API contracts.
- Add/adjust Playwright coverage in the same PR as user-facing behavior changes.

### Merge/quality gates per PR

- Backend Python changes follow `/python-tdd-with-uv` (RED -> GREEN -> REFACTOR).
- Targeted `uv run pytest` and relevant Playwright specs pass for the slice.
- No known role/privacy regressions in trainee-facing API/WS payloads.
- PR cannot merge until `/babysitting-pr` loop confirms green checks and merge-ready status.

### Stacked dependency graph

```mermaid
flowchart TD
  pr01["PR01 #18 ws-01"] --> pr02["PR02 #19 ws-02"]
  pr02 --> pr03["PR03 #20 ws-03"]
  pr03 --> pr04["PR04 #21 ws-04"]
  pr04 --> pr05["PR05 #22 ws-05"]
  pr05 --> pr06[PR06 LearningWorkflows]
  pr06 --> pr07[PR07 CohortsExports]
  pr07 --> pr08[PR08 NotesRemindersTimer]
  pr08 --> pr09[PR09 BadgesAnalyticsFeedback]
  pr09 --> pr10[PR10 HardeningAndTests]
```
*(PR numbers for PR06–PR10 appear when those PRs are opened; update diagram with the stack table.)*

### `/split-to-prs` readiness checklist

- Approve the split map before any branch/commit/push/PR operations.
- Save a recoverable backup ref before moving work between slices.
- Stage only named files/hunks for each slice (`no git add .` / `no git add -A`).
- Report PR titles/URLs and remaining working-tree status after execution, and refresh **[GitHub PR stack](#github-pr-stack-open--update-when-retargetedmerged)** plus mermaid labels for opened slices.

## PR babysitting policy (locked)

`/babysitting-pr` is mandatory for **every PR** in the 10-PR stacked chain before merge.

### Execution loop

- Loop model: `check -> fix -> push -> re-check`.
- Commands used during loop:
  - `gh pr view --json number,title,state,mergeable,reviewDecision,statusCheckRollup,comments,reviews`
  - `gh pr checks`
  - `gh run view <run-id> --log-failed`
  - `gh pr checks --watch`
- Loop is **unlimited** until one of the stop conditions is met.

### Stop conditions

- All checks pass, review/conflict status is acceptable, and PR is merge-ready.
- A blocker needs product/design clarification; escalate to user and pause automated fixing.

### Safeguards

- Never force-push to shared PR branches.
- Never use destructive git operations (no hard reset/clean/history rewrite).
- Do not weaken tests/assertions merely to make CI pass unless behavior change is intentional and approved.

### Testing flow note

CI-failure triage and remediation is part of the normal per-PR execution flow, not a final end-of-project phase.
