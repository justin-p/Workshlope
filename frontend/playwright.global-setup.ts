import { execFileSync } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import type { FullConfig } from "@playwright/test"

/**
 * Fresh Postgres + migrated backend state before local E2E.
 * Skip inside Docker (`/.dockerenv`): CI/workflows reset the compose stack on the host.
 * Opt out anytime: SKIP_E2E_BACKEND_RESET=1
 */
async function globalSetup(_config: FullConfig): Promise<void> {
  if (process.env.SKIP_E2E_BACKEND_RESET === "1") return
  if (existsSync("/.dockerenv")) return

  const frontendDir = path.dirname(fileURLToPath(import.meta.url))
  const repoRoot = path.resolve(frontendDir, "..")
  const script = path.join(repoRoot, "scripts", "e2e-backend-reset.sh")

  execFileSync("bash", [script], { cwd: repoRoot, stdio: "inherit" })
}

export default globalSetup
