<div align="center">
  <img src="frontend/public/assets/images/workshlope-logo.svg" alt="Workshlopé" width="1120" />
</div>

---

This repository now uses the [`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template) as its baseline.

## Quick start (Docker-first)

1. Create local secrets/config from the tracked defaults:

```bash
cp .env .env.local
```

1. Edit `.env.local` and set secure values for:
   - `SECRET_KEY`
   - `FIRST_SUPERUSER_PASSWORD`
   - `POSTGRES_PASSWORD`

1. Start the stack with your local env file:

```bash
docker compose --env-file .env.local up -d --build
```

1. Open:
   - Frontend: `http://localhost:5173`
   - API docs: `http://localhost:8000/docs`
   - Auth.js bridge health: `http://localhost:3001/api/bridge/health`

## GitHub sign-in (pending-approval flow)

This stack supports an optional "Continue with GitHub" sign-in via a sidecar
[Auth.js](https://authjs.dev) (NextAuth v5) service. New GitHub identities do
**not** automatically receive an account. Instead, the first time someone
signs in with a previously-unknown GitHub account:

1. The Auth.js service handles the OAuth handshake with GitHub.
2. It mints a short-lived bridge token (HS256, shared secret with the FastAPI
   backend) and redirects the browser to `/auth/callback` on the frontend.
3. The FastAPI backend verifies the bridge token. If the GitHub identity is
   already linked to an active local user, it issues an API JWT and the user
   is signed in. Otherwise it creates a `pending_github_login` row and the
   frontend shows an "awaiting admin approval" screen.
4. A superuser opens the **Pending GitHub** tab in `/admin` and chooses one of
   two approval paths per request:
   - **Link to an existing user** — pick a local user from the dropdown; the
     GitHub identity is attached to that user.
   - **Create a new user** — a new local user is created from the GitHub
     profile email/full-name (no usable password, GitHub-only sign-in).
   - Or **Deny** — the pending row is deleted and no user is created.
5. On the next GitHub login from that account, the user is signed in
   automatically.

`is_active=false` always blocks sign-in, even when the GitHub account is
linked.

To run the bridge service locally, set the following in `.env.local`:

- `GITHUB_BRIDGE_SECRET` — strong random shared secret; used by both
  `authjs-service` and the FastAPI backend.
- `authjs-service/.env` — `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`,
  `AUTH_SECRET`, `BRIDGE_SECRET` (= `GITHUB_BRIDGE_SECRET`),
  `FRONTEND_CALLBACK_URL=http://localhost:5173/auth/callback`.

## GitHub App setup for lesson sync

The workshop lesson sync card in `/workshops` supports app installation and
repo-access prompts, but a platform admin must bootstrap the GitHub App first.
The app now uses a private-safe sync model: manual refresh actions in the UI
plus backend periodic polling.

### GitHub App page checklist (local)

Use this checklist when creating/editing the GitHub App:

- **General**
  - Homepage URL: `http://localhost:5173`
- **Identifying and authorizing users**
  - Callback URL: `http://localhost:3001/api/auth/callback/github`
  - `Request user authorization (OAuth) during installation`: leave **off** for lesson-sync installs.
  - `Enable Device Flow`: **off**.
- **Post installation**
  - Setup URL: `http://localhost:5173/workshops` (recommended).
  - `Redirect on update`: optional (usually off for local).
- **Webhook**
  - Leave webhook inactive/empty for this project.
  - Do **not** configure webhook URL/secret; sync uses polling now.
- **Permissions**
  - Repository permissions:
    - `Contents`: **Read-only**
    - `Metadata`: **Read-only** (GitHub may mark this mandatory)
  - Keep unrelated repository permissions (`Actions`, `Administration`, etc.) as **No access** unless explicitly needed.
- **Subscribe to events**
  - None required for lesson sync in polling mode.

1. Create/register the GitHub App in GitHub:
   - [Creating GitHub Apps](https://docs.github.com/en/apps/creating-github-apps)
2. **Obtain App ID and private key (GitHub UI).** GitHub never shows the PEM again after generation; you must use the Developer settings screens:
   - Open **GitHub → Settings → Developer settings → GitHub Apps** (for a personal app) **or** your org’s **Settings → Developer settings → GitHub Apps**.
   - Select your app. Note **App ID** at the top of the app page; set `GITHUB_APP_ID` to that numeric value.
   - In the **Private keys** section, click **Generate a private key**. GitHub downloads a `.pem` file **once**; store it securely. If you lose it, generate a new key and revoke the old one in the same UI.
   - Put the PEM into `.env.local` as `GITHUB_APP_PRIVATE_KEY`:
     - **Option A:** paste the whole file contents (including `-----BEGIN RSA PRIVATE KEY-----` / `END` lines) on one line with newlines escaped as `\n`.
     - **Option B:** use a `.env`-compatible multiline value if your loader supports it; the backend normalizes `\n` in the string.
   - See also: [Managing private keys for GitHub Apps](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-github-apps/managing-private-keys-for-github-apps).
3. Configure backend env in `.env.local`:
   - Required for app auth/polling: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`
   - Required for deterministic install kickoff link in UI (pick one):
     - `GITHUB_APP_SLUG` (for example `lesson-bot`)
     - `GITHUB_APP_INSTALL_URL` (full URL override)

   **`GITHUB_APP_SLUG`:** This is the short name part in your GitHub App’s URL (not the numeric ID). You can see it on your app page in GitHub settings. Set `GITHUB_APP_SLUG` if you want users to see the "Install GitHub App" link before your first installation. You don’t need to set it if you set `GITHUB_APP_INSTALL_URL` or if all installations already have their slug stored.

   - Optional periodic polling controls:
     - `GITHUB_INSTALLATION_POLL_ENABLED=true`
     - `GITHUB_INSTALLATION_POLL_INTERVAL_SECONDS=300`
     - `GITHUB_INSTALLATION_POLL_REFRESH_REPOSITORIES=true`
4. Rebuild/restart the stack:

```bash
docker compose --env-file .env.local up -d --build
```

Behavior in the workshop sync card:

- If no installation exists and install URL is configured, the card shows
  `Install GitHub App`.
- If no installation exists and no install URL is configured, the card shows a
  setup warning with `Create a GitHub App`.
- If installation uses `selected` repos but none are entitled, the card blocks
  sync and shows `Grant repository access`.
- If installations exist but the Installation ID box is blank, it is prefilled from the API (`GET …/installations`; use **Refresh lists** after a new GitHub App install).

## Upstream template docs

## Technology Stack and Features

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) for the Python backend API.
  - 🧰 [SQLModel](https://sqlmodel.tiangolo.com) for the Python SQL database interactions (ORM).
  - 🔍 [Pydantic](https://docs.pydantic.dev), used by FastAPI, for the data validation and settings management.
  - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
- 🚀 [React](https://react.dev) for the frontend.
  - 💃 Using TypeScript, hooks, [Vite](https://vitejs.dev), and other parts of a modern frontend stack.
  - 🎨 [Tailwind CSS](https://tailwindcss.com) and [shadcn/ui](https://ui.shadcn.com) for the frontend components.
  - 🤖 An automatically generated frontend client.
  - 🧪 [Playwright](https://playwright.dev) for End-to-End testing.
  - 🦇 Dark mode support.
- 🐋 [Docker Compose](https://www.docker.com) for development and production.
- 🔒 Secure password hashing by default.
- 🔑 JWT (JSON Web Token) authentication.
- 📫 Email based password recovery.
- 📬 [Mailcatcher](https://mailcatcher.me) for local email testing during development.
- ✅ Tests with [Pytest](https://pytest.org).
- 📞 [Traefik](https://traefik.io) as a reverse proxy / load balancer.
- 🚢 Deployment instructions using Docker Compose, including how to set up a frontend Traefik proxy to handle automatic HTTPS certificates.
- 🏭 CI (continuous integration) and CD (continuous deployment) based on GitHub Actions.

### Dashboard Login

[![API docs](img/login.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Dashboard - Admin

[![API docs](img/dashboard.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Dashboard - Items

[![API docs](img/dashboard-items.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Dashboard - Dark Mode

[![API docs](img/dashboard-dark.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Interactive API Documentation

[![API docs](img/docs.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Update From the Original Template

To get the latest changes from the original template.

- Make sure you added the original repository as a remote, you can check it with:

```bash
git remote -v

origin    git@github.com:octocat/my-full-stack.git (fetch)
origin    git@github.com:octocat/my-full-stack.git (push)
upstream    git@github.com:fastapi/full-stack-fastapi-template.git (fetch)
upstream    git@github.com:fastapi/full-stack-fastapi-template.git (push)
```

- Pull the latest changes without merging:

```bash
git pull --no-commit upstream master
```

This will download the latest changes from this template without committing them, that way you can check everything is right before committing.

- If there are conflicts, solve them in your editor.

- Once you are done, commit the changes:

```bash
git merge --continue
```

### Configure

You can then update configs in the `.env` files to customize your configurations.

Before deploying it, make sure you change at least the values for:

- `SECRET_KEY`
- `FIRST_SUPERUSER_PASSWORD`
- `POSTGRES_PASSWORD`

You can (and should) pass these as environment variables from secrets.

Read the [deployment.md](./deployment.md) docs for more details.

### Generate Secret Keys

Some environment variables in the `.env` file have a default value of `changethis`.

You have to change them with a secret key, to generate secret keys you can run the following command:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the content and use that as password / secret key. And run that again to generate another secure key.

## Backend Development

Backend docs: [backend/README.md](./backend/README.md).

## Frontend Development

Frontend docs: [frontend/README.md](./frontend/README.md).

## Deployment

Deployment docs: [deployment.md](./deployment.md).

## Development

General development docs: [development.md](./development.md).

This includes using Docker Compose, custom local domains, `.env` configurations, etc.

## License

The Full Stack FastAPI Template is licensed under the terms of the MIT license.
