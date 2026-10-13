# Instructions for Claude

## Rules

- Never merge a pull request.
- Never push to `main`.
- Never change repository settings.
- Never deploy anything.
- Stop after pushing your branch.

## After each PR

After each PR, give a file-by-file explanation of the changes in simple words.

## Working on this repo

- The design is in `docs/specs/`. Implement one ticket per branch, named
  `feature/HDP-<n>-<short-desc>` (or `fix/` or `chore/`).
- Commit messages start with the ticket key, for example `HDP-2: add sap_date helper`.
- Before pushing, run `ruff check .`, `ruff format --check .` and `pytest -m "not integration"`.
- Local Spark needs Java 17: run `./scripts/setup_env.sh`, then
  `export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64` and `source .venv/bin/activate`.
