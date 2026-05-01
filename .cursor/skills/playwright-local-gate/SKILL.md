---
name: playwright-local-gate
description: Ensure Playwright-related changes are validated locally before commit/PR updates. Use when modifying frontend tests, Playwright config, Playwright Docker setup, or babysitting CI failures around Playwright.
---

# Playwright Local Gate

Run this workflow before committing Playwright-related changes and during `/babysitting-pr` loops.

## Trigger Conditions

Use this skill when staged or modified files include:

- `frontend/tests/**`
- `frontend/playwright.config.ts`
- `frontend/Dockerfile.playwright`
- `.github/workflows/playwright.yml`

## Required Local Validation

1. Start backend required by frontend tests:

```bash
/usr/bin/docker compose --env-file .env.local up -d --wait backend
```

2. Run Playwright from `frontend`:

```bash
cd frontend
bunx playwright test tests/workshop.spec.ts --project=chromium --fail-on-flaky-tests
```

3. If the touched test is not `workshop.spec.ts`, run only touched specs first:

```bash
cd frontend
bunx playwright test tests/<changed-spec>.spec.ts --project=chromium --fail-on-flaky-tests
```

4. Before commit/PR update, run a broader check:

```bash
cd frontend
bunx playwright test --project=chromium --fail-on-flaky-tests
```

5. If tests fail, do not commit. Fix, rerun, then proceed.

## CI Babysitting Rule

When `/babysitting-pr` reports failing Playwright shards:

- Reproduce locally with the same command first.
- Fix selectors/waits only as needed for deterministic behavior.
- Re-run local Playwright before pushing.

## Notes

- If local run fails with missing browser binaries, install once:

```bash
cd frontend
bunx playwright install chromium
```

- If local run fails with permissions in `frontend/test-results` or `frontend/blob-report`, clean these paths before retry.
