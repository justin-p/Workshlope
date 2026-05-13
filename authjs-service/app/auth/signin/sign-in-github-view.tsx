"use client"

import { signIn } from "next-auth/react"
import { useSearchParams } from "next/navigation"
import { useEffect, useRef, useState } from "react"

const SIGNIN_ERRORS: Record<string, string> = {
  default: "Unable to sign in.",
  Signin: "Try signing in with a different account.",
  OAuthSignin: "Try signing in with a different account.",
  OAuthCallbackError: "Try signing in with a different account.",
  OAuthCreateAccount: "Try signing in with a different account.",
  EmailCreateAccount: "Try signing in with a different account.",
  Callback: "Try signing in with a different account.",
  OAuthAccountNotLinked:
    "To confirm your identity, sign in with the same account you used originally.",
  EmailSignin: "The e-mail could not be sent.",
  CredentialsSignin:
    "Sign in failed. Check the details you provided are correct.",
  SessionRequired: "Sign in to access this page.",
}

export function SignInGithubView() {
  const searchParams = useSearchParams()
  const callbackUrl = searchParams.get("callbackUrl") || "/"
  const provider = searchParams.get("provider")
  const errorCode = searchParams.get("error")
  const errorMessage =
    errorCode &&
    (SIGNIN_ERRORS[errorCode] ?? SIGNIN_ERRORS.default)

  const autoStarted = useRef(false)
  const [autoStarting, setAutoStarting] = useState(false)

  useEffect(() => {
    if (errorCode) return
    if (provider !== "github") return
    if (autoStarted.current) return
    autoStarted.current = true
    setAutoStarting(true)
    void signIn("github", { callbackUrl })
  }, [provider, callbackUrl, errorCode])

  const busy = Boolean(autoStarting && !errorCode)

  return (
    <div className="auth-signin-shell">
      <aside className="auth-signin-promo" aria-hidden="true">
        <img
          src="/assets/images/workshlope-logo.svg"
          alt="Workshlopé"
          className="auth-signin-logo auth-signin-logo--for-light-bg"
        />
        <img
          src="/assets/images/workshlope-logo-light.svg"
          alt=""
          className="auth-signin-logo auth-signin-logo--for-dark-promo"
        />
      </aside>
      <section className="auth-signin-panel">
        <div className="auth-signin-panel-inner">
          {errorMessage ? (
            <div className="auth-signin-error" role="alert">
              {errorMessage}
            </div>
          ) : null}
          {busy ? (
            <p className="auth-signin-status" role="status">
              Redirecting to GitHub…
            </p>
          ) : null}
          <h1 className="auth-signin-title">Sign in</h1>
          <p className="auth-signin-sub">
            Use your GitHub account to continue to the workshop app.
          </p>
          <button
            type="button"
            className="auth-signin-github-btn"
            disabled={busy}
            onClick={() => void signIn("github", { callbackUrl })}
          >
            <img
              src="https://authjs.dev/img/providers/github.svg"
              alt=""
              width={20}
              height={20}
              className="auth-signin-github-icon"
            />
            Continue with GitHub
          </button>
        </div>
      </section>
    </div>
  )
}
