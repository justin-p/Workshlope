import type { APIRequestContext } from "@playwright/test"

type Email = {
  id: number
  recipients: string[]
  subject: string
}

function mailcatcherMessagesUrl(): string {
  const base = process.env.MAILCATCHER_HOST
  if (!base?.trim()) {
    throw new Error(
      "MAILCATCHER_HOST is unset - set http://localhost:1080 for host Playwright or run scripts/e2e-backend-reset.sh (Mailcatcher in compose)",
    )
  }
  return `${base.replace(/\/+$/, "")}/messages`
}

/** Match Mailcatcher recipient strings (`user@x`, `<user@x>`, quoted forms). */
export function mailFiltersToMailbox(email: string): (e: Email) => boolean {
  const norm = email.trim().toLowerCase()
  const strip = (r: string) =>
    r
      .replace(/^<+|>$/g, "")
      .replace(/^["']+|["']+$/g, "")
      .trim()
      .toLowerCase()
  return (e) => {
    if (e.recipients.some((r) => strip(r) === norm)) return true
    const subj = e.subject.toLowerCase()
    return (
      subj.includes(norm) &&
      /password\s+recovery|recovery\s+for\s+user/i.test(e.subject)
    )
  }
}

async function findEmail({
  request,
  filter,
}: {
  request: APIRequestContext
  filter?: (email: Email) => boolean
}) {
  const messagesUrl = mailcatcherMessagesUrl()
  const response = await request.get(messagesUrl)

  if (!response.ok()) {
    throw new Error(
      `Mailcatcher GET ${messagesUrl} returned ${response.status()} ${response.statusText()}`,
    )
  }

  const raw = await response.text()
  let emails: unknown
  try {
    emails = JSON.parse(raw)
  } catch {
    throw new Error(
      `Mailcatcher at ${messagesUrl} did not return JSON (got snippet: ${raw.slice(0, 160).replace(/\s+/g, " ")})`,
    )
  }

  if (!Array.isArray(emails)) {
    throw new Error(`Mailcatcher at ${messagesUrl} returned non-array JSON`)
  }

  const list = emails as Email[]
  const filtered = filter ? list.filter(filter) : [...list]

  const email = filtered[filtered.length - 1]

  if (email) {
    return email as Email
  }

  return null
}

export function findLastEmail({
  request,
  filter,
  timeout = 5000,
}: {
  request: APIRequestContext
  filter?: (email: Email) => boolean
  timeout?: number
}) {
  const timeoutPromise = new Promise<never>((_, reject) =>
    setTimeout(
      () => reject(new Error("Timeout while trying to get latest email")),
      timeout,
    ),
  )

  const checkEmails = async () => {
    while (true) {
      const emailData = await findEmail({ request, filter })

      if (emailData) {
        return emailData
      }
      // Wait for 100ms before checking again
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
  }

  return Promise.race([timeoutPromise, checkEmails()])
}
