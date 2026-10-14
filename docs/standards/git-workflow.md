# Git workflow standard

Applies to all code, configuration, SQL and notebooks in this repository. Developers work in
their own Databricks Git folder (a personal clone of the repository inside the workspace).
Nobody needs a local clone.

## Branches

| Branch | What it holds | Created from | Merged into | Runs in |
| --- | --- | --- | --- | --- |
| `main` | Production. Every merge is a release, tagged `vX.Y.Z`. | (exists) | (end of the line) | PROD |
| `develop` | All finished work. Always runnable. | `main`, once | `release/X.Y.Z` | DEV |
| `feature/HDP-<n>-<desc>` | One ticket: new logic, tables, rules. | `develop` | `develop` | your Git folder |
| `bugfix/HDP-<n>-<desc>` | A defect found in DEV or SIT. | `develop` or the open `release/*` | the branch it came from | your Git folder |
| `chore/HDP-<n>-<desc>` | Tooling, CI, docs; no business logic. | `develop` | `develop` | your Git folder |
| `release/X.Y.Z` | Code freeze for testing; only bug fixes go in. | `develop` | `main`, then back into `develop` | SIT, then UAT |
| `hotfix/HDP-<n>-<desc>` | Urgent production fix. | `main` | `main`, then `develop` | PROD |
| `exp/<name>` | Throwaway experiment. | anywhere | never; abandoned after use | your Git folder |

DEV is the `halvern_dev` catalog. SIT, UAT and PROD deployments by branch arrive with CI/CD
(Databricks Asset Bundles). Scheduled jobs never run from a personal Git folder.

## Who merges what, and where

| Merge | Where | Who | Before merging |
| --- | --- | --- | --- |
| `develop` into your branch (sync) | Databricks Git folder | developer | always, right before the next row |
| feature, bugfix, chore into `develop` | Databricks Git folder | developer | `tools/run_checks` PASS, the ticket's validation PASS |
| new `release/X.Y.Z` from `develop` | Databricks Git folder (Create Branch) | lead | code freeze agreed |
| `release/X.Y.Z` into `main` | Pull request on GitHub | lead | 1 approval, CI green, SIT and UAT signed off |
| `main` back into `develop` | Databricks Git folder | lead | after every release or hotfix |

Databricks Git folders can branch, commit, push, pull, merge, rebase and resolve conflicts.
They have no pull requests and no approvals. That is why the one merge that changes production
goes through a pull request. Many teams also require pull requests into `develop` (in Azure
DevOps or GitHub). This repository lets developers merge into `develop` from Databricks and
protects `develop` with checks before merging and a no-force-push rule.

## Daily work in Databricks

1. **Start.** Git folder → branch button → switch to `develop` → **Pull**. Then **Create
   Branch**: `feature/HDP-<n>-<desc>`, base `develop`.
2. **Work.** Edit files and notebooks. Databricks saves as you type.
3. **Commit and push often.** Git dialog → review the changed files → message
   `HDP-<n>: <what changed>` → **Commit & Push**. Every push runs CI on GitHub; GitHub emails
   you only when it fails.
4. **Check.** Run `tools/run_checks` and the ticket's validation notebook.
5. **Sync.** Still on your branch: Git dialog → **⋮** → **Merge** → choose `develop`. This brings
   everyone else's finished work into your branch. On a conflict, follow the conflict policy.
6. **Check again** after the sync: `tools/run_checks`.
7. **Merge into develop.** Switch to `develop` → **Pull** → **⋮** → **Merge** → choose your
   branch. Read the dialog before you confirm: your branch goes *into* `develop`. Databricks
   pushes `develop`.
8. **Next ticket.** Start again at step 1. The lead removes merged branches on GitHub from time
   to time (Databricks cannot delete remote branches).

Merges create merge commits. Never **Rebase** a branch that someone else uses: rebase rewrites
history and force-pushes.

## Conflict policy

Conflicts are found and fixed on your own branch, never on `develop`, `release/*` or `main`.
That is why you sync `develop` into your branch (step 5) before you merge (step 7).

### Default: resolve on your branch

Use this for most conflicts: both sides made sensible changes to the same lines.

1. Sync (step 5). The Git dialog lists the files in conflict.
2. Ask the other developer which logic is right, or whether both are needed. Never guess.
3. In the conflict editor keep the right lines (**Keep all current**, **Take all incoming**, or edit
   by hand), delete every `<<<<<<<`, `=======` and `>>>>>>>` marker, **Mark As Resolved**, then
   **Continue Merge**.
4. Run `tools/run_checks` and the ticket's validation again. A merge that Git accepts can still be
   wrong: two DQ rules with the same id, or a column removed on one side and used on the other.
5. Merge into `develop` (step 7).

### Exception: start a fresh branch

Use this when resolving is riskier than redoing:

- the code you changed was restructured on `develop` (moved, renamed or split), so your old lines
  no longer exist in that shape;
- your branch is far behind `develop`, or carries commits that must not reach `develop` (debug
  cells, experiments, half-finished work);
- your real change is small compared with the conflicts.

Steps: **Abort** the merge → switch to `develop` → **Pull** → **Create Branch**
`<old name>-v2` → re-apply only the intended change on the new code → run checks → merge into
`develop`. The old branch is abandoned; the lead deletes it on GitHub.

### Protected branches

A branch that takes no direct commits cannot hold a resolution. For example, a `release/X.Y.Z` →
`main` pull request that conflicts with a hotfix: the lead resolves it on a temporary branch made
for that merge (GitHub offers to create one), never on `main`. This is practised on day 5.

## Commits

- Start with the ticket key: `HDP-7: add run reconciliation`.
- One logical change per commit. No secrets, no data files.
- Notebooks are saved in source format (`.py`), which never stores cell output. Set it once:
  Settings → Developer → Editor settings → default notebook format → Source.

## Releases and hotfixes (lead)

Release:

1. In Databricks, create `release/X.Y.Z` from `develop`. From now on only `bugfix/` branches
   merge into it; new features keep going into `develop`.
2. Deploy the release branch to SIT, then UAT. Fix defects on `bugfix/` branches from the release
   branch.
3. After sign-off, open a pull request `release/X.Y.Z` → `main` on GitHub. 1 approval, CI green,
   merge commit.
4. Tag `vX.Y.Z` on `main` (GitHub → Releases → Draft a new release).
5. In Databricks, on `develop`: **⋮** → **Merge** → `main`, so `develop` gets the release fixes.

Hotfix: `hotfix/HDP-<n>-<desc>` from `main` → fix → pull request into `main` → tag the next patch
version → merge `main` back into `develop` in Databricks.

## Repository settings (owner, once)

Set once on GitHub by the repository owner. In company projects the DevOps or platform team owns
these settings; developers never change them.

- General → Default branch → `develop`.
- Rules → Rulesets → `protect-main`, target branch `main`: require a pull request with 1 approval,
  dismiss stale approvals on new commits, require status checks `lint` and `test`, block force
  pushes, restrict deletions.
- Rules → Rulesets → `protect-develop-release`, targets `develop` and `release/**`: block force
  pushes, restrict deletions. (No pull request rule, so merges from Databricks can push.)
- A second GitHub account added as a collaborator approves release pull requests.

## Why this model (decision record, HDP-6)

- **Context.** Several developers, a DEV → SIT → UAT → PROD path, and finance numbers that need
  test sign-off on a frozen version before production changes. Developers work in Databricks.
- **Options.** Trunk-based (only `main` and short branches; fastest, but needs strong automated
  tests and feature flags to release half-finished work safely) or GitFlow-style (`develop` and
  `release/*`; slower, but gives a code freeze for SIT and UAT).
- **Decision.** GitFlow-style. Phase 1 used trunk-based with squash-merged pull requests into
  `main`; this replaces it from HDP-6.
- **Consequences.** More branches to manage, back-merges after every release, and a risk that
  `develop` drifts far ahead of `main`. Frequent small releases keep that drift small.
