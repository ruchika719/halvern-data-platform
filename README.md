# Halvern Data Platform

A lakehouse for a synthetic pharma company's sales, inventory and P&L data. Phase 1
covers the sales slice: SAP billing from two SAP systems, customer and item master
data, FX rates, wholesaler 867 sales files and reference mappings. Everything runs on
GitHub and locally. Phase 1 uses no Azure, no Databricks and no secrets, and all data
is synthetic.

The full design is in [`docs/specs/spec-01-foundation.md`](docs/specs/spec-01-foundation.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `src/halvern/` | Platform code: `common/` pure helpers, `contracts/` loader and validator |
| `generator/halvern_gen/` | Synthetic data generator (`halvern-gen` CLI) |
| `contracts/` | One YAML data contract per source object |
| `reference/` | Small static reference CSVs |
| `tests/` | `unit/`, `contracts/`, `generator/` test suites |
| `docs/` | Specs and architecture decision records |
| `infra/`, `adf/`, `resources/` | Phase 2 placeholders (Terraform, ADF, Databricks Asset Bundles) |
| `data/` | Generated output, git-ignored |

## Setup

You need Python 3.12 and Java 17 (local Spark 3.5 runs on Java 17).

```bash
./scripts/setup_env.sh          # installs Java 17 if missing, creates .venv, installs deps
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
source .venv/bin/activate
```

You can also set it up by hand with `python3.12 -m venv .venv` and
`pip install -r requirements-dev.txt`.

## Running checks

These are the same checks CI runs:

```bash
ruff check .
ruff format --check .
pytest -m "not integration"
```

Pytest markers are `unit`, `contract`, `generator` and `integration`. CI skips
integration tests for now and fails if coverage drops below 70%.

## Generating data

The `halvern-gen` generator is added in HDP-4. Usage docs and the mess profiles
(`clean`, `realistic`, `chaos`) are documented in HDP-5.

## Branching and pull requests

- Trunk-based: `main` is always releasable.
- Branches are short-lived and named `feature/HDP-<n>-<short-desc>`, `fix/HDP-<n>-...` or
  `chore/HDP-<n>-...`.
- Commit messages start with the ticket key, for example `HDP-2: add sap_date helper and tests`.
- GitHub Issues titled `HDP-<n>` act as tickets.
- PRs use the template in `.github/pull_request_template.md`. They squash-merge only,
  and the branch is deleted after merge.
- CI jobs `lint` and `test` must pass before merging.
