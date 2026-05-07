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

## Workshop Delivery Guardrails

- Treat `workshop_lessons_&_sessions_aa012042.plan.md` as the detailed delivery map; keep `AGENTS.md` as execution rules and safety checks.
- For stacked workshop slices, follow one merge path only:
  - retarget/rebase each PR toward `main`, or
  - merge remaining stack branches into `main` in order with explicit merge commits.
- After merging any workshop stack, always run:
  - `gh pr view <n> --json number,baseRefName,headRefName,state,mergedAt`
  - `git rev-list --count main..<stack-tip-branch>` (must be `0`)

## PR Babysitting Policy (Required)

- For every PR intended for `main`, run a fix loop until green:
  - `gh pr view --json number,title,state,mergeable,reviewDecision,statusCheckRollup,comments,reviews`
  - `gh pr checks`
  - `gh run view <run-id> --log-failed`
  - `gh pr checks --watch`
- Do not merge with pending/failing checks unless the user explicitly requests an override.
