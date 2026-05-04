import type { Page } from "@playwright/test"
import { expect } from "@playwright/test"

const DEFAULT_MS = 15_000

/**
 * Match success toasts from `useCustomToast`: `toast.success("Success!", { description })`.
 * Sonner mounts under `[data-sonner-toaster]`; copy may be in `[data-description]`.
 */
export async function expectSuccessToastDescription(
  page: Page,
  description: string | RegExp,
  options?: { timeout?: number },
) {
  const timeout = options?.timeout ?? DEFAULT_MS
  const toast = page
    .locator("[data-sonner-toast]")
    .filter({ hasText: description })
  await expect(toast.first()).toBeVisible({ timeout })
}
