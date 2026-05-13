# Auth Bridge service

A small Next.js + Auth.js (NextAuth v5) service that performs the GitHub OAuth
handshake on behalf of the FastAPI app and forwards a signed **bridge token**
back to the React frontend.

## Flow

```
React frontend   ─────►  /api/auth/signin?provider=github             (this service)
GitHub OAuth     ◄────►  /api/auth/callback/github                    (this service)
                 ─────►  /api/bridge?callbackUrl=...                  (this service)
                 ─────►  <frontend>/auth/callback?bridge_token=<jwt>  (React)
                 ─────►  POST /api/v1/oauth/github/bridge             (FastAPI)
                          - already linked + active -> JWT, signed in.
                          - unknown -> pending_approval (admin must approve).
```

The FastAPI backend never auto-creates users from GitHub: any first-time
GitHub login is recorded as a pending request that an admin must approve from
the **Pending GitHub** tab in `/admin`. See the top-level `README.md` for
details.

## Local setup

1. Copy `.env.example` to `.env.local` and fill in:
   - `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` (OAuth app callback:
     `http://localhost:3001/api/auth/callback/github`).
   - `AUTH_SECRET` (`openssl rand -base64 32`).
   - `GITHUB_BRIDGE_SECRET` MUST match `GITHUB_BRIDGE_SECRET` in the FastAPI
     backend's `.env`.
2. Install: `npm install`
3. Run: `npm run dev` (listens on `http://localhost:3001`).
4. Set `VITE_AUTHJS_URL=http://localhost:3001` in `frontend/.env`.

The browser opens **`/auth/signin`** on this host (styled like the main SPA), which then calls Auth.js to start GitHub OAuth. Legacy **`/api/auth/signin`** redirects there when configured.

## Production

The included Dockerfile produces a `next start`-ready image. Deploy behind a
reverse proxy and ensure `AUTH_URL` matches the public URL.
