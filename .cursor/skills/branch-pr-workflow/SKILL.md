---
name: branch-pr-workflow
description: Enforce proper branch, commit, push, and PR workflow for delivery slices. Use whenever making implementation changes.
---

# Branch + PR Workflow

## Purpose

Prevent direct-to-main drift and keep each delivery slice reviewable.

## Required flow

1. Start cleanly from `main`:

```bash
git checkout main
git pull
```

2. Create/switch to a feature branch before edits:

```bash
git checkout -b <feature-branch>
```

3. Implement, validate, and sync `PLAN.md` for meaningful changes.

4. Commit on the feature branch only:

```bash
git add <targeted-files>
git commit -m "<message>"
```

5. Push and open PR:

```bash
git push -u origin <feature-branch>
gh pr create --title "<title>" --body "<body>"
```

## Superseding PRs

If a new PR supersedes an older open PR:

- comment on old PR that it is superseded (link new PR)
- comment on new PR with consolidation note (link old PR)
- close the old PR

## Never do

- never commit on `main` unless user explicitly approves
- never push to `main` unless user explicitly approves
- never leave overlapping active PRs without supersession notes
