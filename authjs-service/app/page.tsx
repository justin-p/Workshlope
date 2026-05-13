export default function Home() {
  return (
    <main className="auth-bridge-page">
      <h1 className="auth-bridge-title">Auth Bridge</h1>
      <p className="auth-bridge-lead">
        This service handles the GitHub OAuth handshake and mints bridge tokens
        for the FastAPI backend. End users should not interact with this UI
        directly &mdash; the FastAPI frontend redirects through it.
      </p>
      <p className="auth-bridge-p">
        The SPA opens{" "}
        <code className="auth-bridge-code">
          /auth/signin?provider=github&amp;callbackUrl=&lt;frontend&gt;/auth/callback
        </code>{" "}
        (themed Next page), which continues with Auth.js{" "}
        <code className="auth-bridge-code">POST /api/auth/signin/github</code>.
      </p>
    </main>
  )
}
