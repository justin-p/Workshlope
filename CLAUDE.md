<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **testing** (4234 symbols, 6377 relationships, 59 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/testing/context` | Codebase overview, check index freshness |
| `gitnexus://repo/testing/clusters` | All functional areas |
| `gitnexus://repo/testing/processes` | All execution flows |
| `gitnexus://repo/testing/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Stacked PR Merge Safeguard (Required)

- NEVER treat stacked PR merges into non-`main` bases as landed on `main`.
- Before merging stacked PRs, verify each PR base explicitly:
  - `gh pr view <n> --json number,baseRefName,headRefName,state`
- If any PR base is not `main`, do one of:
  - retarget/rebase so the next PR merges to `main`, or
  - merge remaining stack branches into `main` in order with explicit merge commits.
- After merges, prove `main` contains the stack tip:
  - `git checkout main && git pull`
  - `git rev-list --count main..<stack-tip-branch>` must be `0`
  - `git log --oneline --decorate -n 20` must show expected merge commits.

## Change Delivery Guardrails

- Treat `PLAN.md` as the detailed delivery map; keep `AGENTS.md` as execution rules and safety checks.
- Plan-sync is mandatory: whenever code/tests/docs state changes materially, update `PLAN.md` in the same working pass (at minimum `Last synced`, `Latest work`, and/or `Testing` bullets as applicable) before asking to continue or before commit.
- Branch + PR workflow is mandatory for delivery work unless the user explicitly approves direct-to-`main`:
  - before editing, ensure current branch is not `main`; if on `main`, create/switch to a feature branch first,
  - open a PR for each completed slice and share the PR URL,
  - do not merge to `main` locally without explicit user approval.
- Required skills by default for code changes:
  - `/python-tdd-with-uv` for backend Python changes (RED -> GREEN -> REFACTOR via `uv run`).
  - `/playwright-local-gate` for local Playwright validation on behavior/UI changes.
  - `/babysitting-pr` for CI/review merge-readiness loops.
- For stacked change slices, follow one merge path only:
  - retarget/rebase each PR toward `main`, or
  - merge remaining stack branches into `main` in order with explicit merge commits.
- After merging any stacked branch set, always run:
  - `gh pr view <n> --json number,baseRefName,headRefName,state,mergedAt`
  - `git rev-list --count main..<stack-tip-branch>` (must be `0`)
- For split workflows, enforce:
  - approve split map before any branch/commit/push/PR work,
  - stage only targeted files/hunks (no `git add .` / no `git add -A`),
  - report resulting PR URLs and remaining working tree status.

## PR Babysitting Policy (Required)

- For every PR intended for `main`, run a fix loop until green:
  - `gh pr view --json number,title,state,mergeable,reviewDecision,statusCheckRollup,comments,reviews`
  - `gh pr checks`
  - `gh run view <run-id> --log-failed`
  - `gh pr checks --watch`
- Do not merge with pending/failing checks unless the user explicitly requests an override.
- Stop only when:
  - all checks are green and mergeability is acceptable, or
  - a blocker requires product/design input from the user.
- Safety constraints:
  - never force-push shared PR branches,
  - never use destructive history/working-tree operations,
  - never weaken tests just to make CI pass unless behavior change is explicitly approved.
