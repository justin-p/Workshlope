import type { Page } from "@playwright/test"
import { expect } from "@playwright/test"

const DEFAULT_MS = 15_000

function sonnerToastWithText(page: Page, description: string | RegExp) {
  return page.locator("[data-sonner-toast]").filter({ hasText: description })
}

/**
 * Assert a Sonner toast (success or error) shows the given copy.
 * Prefer over page-wide `getByText` for API-driven toasts to avoid accidental DOM matches.
 */
export async function expectSonnerToastDescription(
  page: Page,
  description: string | RegExp,
  options?: { timeout?: number },
) {
  const timeout = options?.timeout ?? DEFAULT_MS
  await expect(sonnerToastWithText(page, description).first()).toBeVisible({
    timeout,
  })
}

/**
 * Success toasts from `useCustomToast`: `toast.success("Success!", { description })`.
 * Sonner mounts under `[data-sonner-toaster]`; copy may live under `[data-description]`.
 */
export async function expectSuccessToastDescription(
  page: Page,
  description: string | RegExp,
  options?: { timeout?: number },
) {
  await expectSonnerToastDescription(page, description, options)
}

/**
 * Error toasts from `useCustomToast`: `toast.error("Something went wrong!", { description })`.
 */
export async function expectErrorToastDescription(
  page: Page,
  description: string | RegExp,
  options?: { timeout?: number },
) {
  await expectSonnerToastDescription(page, description, options)
}

/**
 * Resolves when a matching toast is visible (e.g. `Promise.race` with navigation).
 */
export function waitForSonnerToastDescription(
  page: Page,
  description: string | RegExp,
  options?: { timeout?: number },
): Promise<void> {
  const timeout = options?.timeout ?? DEFAULT_MS
  return sonnerToastWithText(page, description)
    .first()
    .waitFor({ state: "visible", timeout })
}
