---
name: start-and-login
description: Start the local app stack and log into the frontend in Cursor browser. Use when the user asks to open the app, start services, sign in, or verify login locally.
---

# Start And Login

## Purpose

Quickly bring up the local app and ensure the user is logged in through Cursor browser with minimal prompts.

## Default workflow

1. Read `development.md` for the canonical local URLs and startup mode.
2. Start and verify the full stack expected by `development.md`:
   - Run `docker compose ps`.
   - If any core service is missing/down, run `docker compose up -d` (not only `frontend`).
   - Core services: `frontend`, `backend`, `db`, `authjs-service` (and `mailcatcher` when present).
3. Verify service availability with health checks/retries:
   - Frontend: `http://localhost:5173`
   - Backend docs: `http://localhost:8000/docs`
   - Backend API schema: `http://localhost:8000/api/v1/openapi.json`
   - Auth bridge health: `http://localhost:3001/api/bridge/health`
   - Use short retry loop (1-3s waits) until services are ready.
4. If an API endpoint returns `404` unexpectedly during UI actions, treat startup as incomplete/misconfigured:
   - Re-check `docker compose ps`.
   - Re-verify `http://localhost:8000/api/v1/openapi.json`.
   - Collect `docker compose logs backend` before continuing.
5. Open frontend in Cursor browser (`browser_navigate`).
6. Follow browser lock order for interactions:
   - `browser_tabs` (list)
   - `browser_lock`
   - `browser_snapshot`
   - interactions (`browser_click`, `browser_fill`, `browser_type`, `browser_wait_for`)
   - `browser_unlock` only after all actions are done
7. Check for existing logged-in session before any login attempt:
   - Take a snapshot on `/`.
   - If dashboard/home nav appears (e.g. `Dashboard`, `Items`, avatar/menu, settings links), mark session as already logged in.
   - Optionally verify by navigating to `/login`; if redirected back to `/`, keep status as already logged in.
8. Only if not logged in:
   - Navigate to `/login`.
   - Log in with local account (email/password) by default.
   - Do not click GitHub sign-in unless user explicitly asks for GitHub flow.
9. Confirm success by checking for dashboard/home UI and absence of login form.

## Login details

- Read credentials from project env values when needed:
  - `FIRST_SUPERUSER`
  - `FIRST_SUPERUSER_PASSWORD`
- In this repo, defaults are typically `admin@example.com` and `changethis` unless user changed `.env`.

## Interaction rules

- Use short waits (`browser_wait_for` with 1-3 seconds) plus snapshots, not long fixed waits.
- Always perform session detection on `/` before navigating to `/login`.
- If `/login` redirects to `/`, report that session is already authenticated.
- Do not assume only frontend needs startup; backend + db must be available before item CRUD checks.
- Ensure `authjs-service` health endpoint is reachable even when using local login, so the stack is fully ready.
- If login fails, report the visible error text and likely cause (service not ready, bad creds, backend unavailable).

## Response format

When done, report:

- Which services were started/found running
- Which URL was opened
- Whether login was newly performed or already authenticated
- What visible page confirmed success
