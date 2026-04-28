export default function Home() {
  return (
    <main style={{ padding: 32, maxWidth: 640, margin: "0 auto" }}>
      <h1>Auth Bridge</h1>
      <p>
        This service handles the GitHub OAuth handshake and mints bridge tokens
        for the FastAPI backend. End users should not interact with this UI
        directly &mdash; the FastAPI frontend redirects through it.
      </p>
      <p>
        Sign in starts at{" "}
        <code>/api/auth/signin/github?callbackUrl=&lt;frontend&gt;/auth/callback</code>
        .
      </p>
    </main>
  )
}
