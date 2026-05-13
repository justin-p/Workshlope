import type { Metadata } from "next"
import { Suspense } from "react"
import { SignInGithubView } from "./sign-in-github-view"

export const metadata: Metadata = {
  title: "Sign in — Auth Bridge",
}

function SignInFallback() {
  return (
    <div className="auth-signin-shell" aria-busy="true">
      <aside className="auth-signin-promo" aria-hidden="true" />
      <section className="auth-signin-panel">
        <p className="auth-signin-status">Loading…</p>
      </section>
    </div>
  )
}

export default function AuthSignInPage() {
  return (
    <Suspense fallback={<SignInFallback />}>
      <SignInGithubView />
    </Suspense>
  )
}
