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
        Sign in starts at{" "}
        <code className="auth-bridge-code">
          /api/auth/signin/github?callbackUrl=&lt;frontend&gt;/auth/callback
        </code>
        .
      </p>
    </main>
  )
}
