# Interview questions: Git, branching and Databricks Git folders

Plain answers first, then the follow-ups interviewers like. Describe your own project's real
setup when it differs: what matters is that you can explain why it was set up that way.

---

**1. Walk me through your branching strategy.**
GitFlow-style. `main` is production and only changes through a release. `develop` collects
finished features and runs in DEV. Each ticket gets a `feature/` branch from `develop`. At code
freeze the lead cuts `release/X.Y.Z` from `develop`; it goes to SIT and UAT, only bug fixes go in,
and after sign-off it is merged into `main` through a pull request and tagged. Production fixes use
`hotfix/` from `main`, merged back into `develop`.

*Follow-up: why not trunk-based?* Trunk-based is faster, but releasing straight from `main` needs
very strong automated tests and feature flags. Finance numbers needed a frozen version signed off
in SIT and UAT, which a release branch gives you.

---

**2. How do you work with Git inside Databricks?**
Each developer has a Git folder: a clone of the repository in their own workspace folder. In it
you switch or create branches, commit and push, pull, merge and resolve conflicts, all from the
Git dialog. Databricks has no pull requests or approvals, so those happen in the Git provider
(GitHub or Azure DevOps).

*Follow-up: where do scheduled jobs run from?* Never from a personal Git folder. Jobs are deployed
by CI/CD (Databricks Asset Bundles) from a branch or tag, or point at the repository with a fixed
branch or tag, so nobody's half-finished edit can change production.

---

**3. Two developers changed the same notebook. What happens?**
Git merges by line. If they changed different lines, the merge is automatic. If they changed the
same lines, the merge stops with a conflict. The developer who merges second brings `develop`
into their own branch, agrees with the other developer which logic is right, resolves it there,
reruns the tests and pushes. Nobody resolves conflicts on `develop` or `main`.

*Follow-up: why save notebooks as .py source and not .ipynb?* Source format is plain code, so
diffs and conflicts are readable line by line. `.ipynb` is JSON with metadata and possibly cell
outputs, which makes diffs noisy and conflicts harder, and outputs can leak data into Git.

---

**4. Merge, rebase or squash: what is the difference?**
Merge keeps both histories and adds a merge commit; nothing is rewritten. Rebase replays your
commits on top of the other branch: a straight history, but it rewrites commits and needs a force
push, so it is only safe on a branch nobody else uses. Squash turns all commits of a branch into
one commit on the target: a clean history, but the individual commits are gone from that branch.

---

**5. How do you stop untested code from reaching develop or main?**
- CI runs lint and unit tests on every push; the pusher is emailed on failure.
- Before merging into `develop`, the developer runs the same checks on the cluster (a
  run-checks notebook) and the ticket's validation notebook.
- `main` is protected: pull request only, one approval, CI must be green, no force push, no delete.
- SIT and UAT run on the frozen release branch before anything reaches `main`.

---

**6. A release broke production. How do you roll back?**
Code: revert the release merge on `main` with a hotfix branch (or redeploy the previous tag),
then fix forward. Data: Delta time travel and `RESTORE` to the version before the bad run, then
re-run the affected loads once the fix is in. Both are only possible if releases are tagged and
`VACUUM` retention covers the recovery window.

---

**7. What never goes into Git?**
Secrets (they live in Key Vault and are read through secret scopes), data files, notebook outputs,
local caches (`__pycache__`, `.pytest_cache`, `.ruff_cache`) and coverage files. The `.gitignore`
covers the generated files; code review covers the rest.

---

**8. How do you handle settings that differ by environment?**
The same code is promoted unchanged from DEV to PROD. What changes is configuration: catalog
name, cluster size, schedules, passed as job parameters or bundle targets (dev, sit, prod). There
are never environment-specific branches or files edited per environment.

---

**9. Someone force-pushed to a shared branch. What is the damage, and how do you prevent it?**
Commits that others had pulled disappear from the remote; their next pull fails or brings the
deleted work back as conflicts. Recovery: find the lost commits in someone's local copy (or the
provider's activity log) and push them back. Prevention: branch rules that block force pushes and
deletions on `main`, `develop` and `release/*`, and no rebasing of shared branches.

---

**10. How do commits link to tickets?**
Every commit message starts with the ticket key (`HDP-7: ...`); branch names carry it too. Jira and
Azure Boards link commits and branches to the ticket from that key (Azure DevOps uses `AB#<id>`),
so a reviewer or auditor can go from a production change to the requirement.

---

**11. Your feature branch had a conflict. Walk me through exactly what you did.**
(Practise this aloud with your own example.) "I merged the latest `develop` into my feature
branch and got a conflict in the DQ rules file: a colleague had added a rule at the same place,
with the same rule id. I checked with her, kept both rules, renumbered mine, removed the conflict
markers, reran the checks and the validation, and then merged."

*Follow-up: would you ever create a new branch instead?* Yes, when resolving is riskier than
redoing: the code I changed had been restructured on `develop`, or my branch was old and had
debug commits in it. Then I abort, create a fresh branch from the latest `develop`, re-apply only
my real change, run the checks and merge. The old branch is deleted. A new branch is also needed
when the branch in conflict is protected, for example a release branch going into `main`.

---

**12. What is a hotfix and how is it different from a bug fix?**
A hotfix fixes production now: branch from `main`, fix, pull request into `main`, new patch tag,
then merge `main` back into `develop` so the fix is not lost in the next release. A bug fix is
found during DEV or SIT and goes through the normal path (`bugfix/` into `develop` or the open
release branch).

---

**13. How do you deploy notebooks and jobs across environments?**
Databricks Asset Bundles: a `databricks.yml` describes jobs, pipelines and their settings per
target. CI/CD validates and deploys the bundle to DEV when `develop` changes, to SIT and UAT from
the release branch, and to PROD from `main` after approval, running as a service principal. (Built
on day 5.)

---

**14. What is a Databricks Git folder limit you have run into?**
Pull requests and branch deletion are not available inside Databricks; switching branches can
remove notebooks that the target branch does not contain (switching back recreates them with new
IDs); notebook state is cleared on pull; and files over 10 MB cannot be viewed in the UI. Large
repositories can use sparse checkout.
