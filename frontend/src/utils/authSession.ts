const AUTH_SESSION_HINT_KEY = "auth_session_hint"

export const hasAuthSessionHint = () => {
  return localStorage.getItem(AUTH_SESSION_HINT_KEY) === "1"
}

export const setAuthSessionHint = () => {
  localStorage.setItem(AUTH_SESSION_HINT_KEY, "1")
}

export const clearAuthSessionHint = () => {
  localStorage.removeItem(AUTH_SESSION_HINT_KEY)
}
