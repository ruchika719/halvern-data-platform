# Spec 01 — Foundation: repo, CI, data generator, data contracts, core functions

Project: Halvern Data Platform (pharma sales, inventory and P&L lakehouse).
Phase: 1 of 6. Runs on GitHub and in Claude Code only. **No Azure, no Databricks, no secrets in this phase.**
Scope: the sales slice — SAP billing (two SAP systems), customer and item master, FX rates, wholesaler 867 sales files, and reference mappings.

---

## 0. Instructions for the coding agent

1. Implement this spec in **five pull requests, in the order of section 10**. One branch per PR.
2. For each PR: create the branch, implement, run `ruff check .`, `ruff format --check .` and `pytest -m "not integration"` locally, push the branch, and **stop**. The owner reviews and merges before the next PR starts.
3. Keep transformation logic in **pure functions** (input DataFrame or value → output), separate from reading and writing files, so everything is unit-testable.
4. Never hard-code paths, company codes or account numbers inside functions; take them from config or parameters.
5. All timestamps are UTC. All generated data is synthetic; never use real company data.
6. If something in this spec is ambiguous, write the question in the PR description instead of guessing.

---

## 1. Tooling and versions

| Item | Choice | Why |
| --- | --- | --- |
| Python | 3.12 | Matches Databricks Runtime 16.4 LTS |
| Spark | `pyspark==3.5.*` | Matches the Databricks runtime |
| Java (for local Spark) | 17 | Supported by Spark 3.5; install in the environment setup script if missing |
| Tests | `pytest`, `pytest-cov`, `chispa` | DataFrame equality helpers |
| Lint and format | `ruff` (lint + format) | One tool |
| Config | `pyyaml` | Contracts and generator profiles |
| Generator | standard library + `numpy` | Fast, deterministic with seeds |

`pyproject.toml` defines two packages: `halvern` (platform code, under `src/`) and `halvern_gen` (generator, under `generator/`). Pytest markers: `unit`, `contract`, `generator`, `integration` (integration tests are skipped in CI for now).

---

## 2. Repository layout

```
halvern-data-platform/
├── README.md
├── pyproject.toml
├── requirements-dev.txt
├── .gitignore                      # ignores data/, .venv, __pycache__, coverage files
├── .github/
│   ├── workflows/ci.yml
│   ├── pull_request_template.md
│   └── CODEOWNERS
├── docs/
│   ├── specs/spec-01-foundation.md
│   ├── decisions/                  # ADRs, added later
│   └── failure-lab.md              # created in PR 5
├── contracts/                      # one YAML per source object (section 6)
├── reference/                      # small static reference CSVs (section 5.5)
├── src/halvern/
│   ├── __init__.py
│   ├── common/                     # pure helper functions (section 7)
│   └── contracts/                  # contract loader and validator (section 6)
├── generator/halvern_gen/
│   ├── __init__.py
│   ├── cli.py
│   ├── state.py
│   ├── profiles/clean.yaml
│   ├── profiles/realistic.yaml
│   ├── profiles/chaos.yaml
│   ├── sources/master_data.py
│   ├── sources/sap_billing.py
│   ├── sources/fx.py
│   ├── sources/wholesalers.py
│   ├── mess.py
│   └── answer_key.py
├── tests/
│   ├── conftest.py                 # local SparkSession fixture
│   ├── unit/
│   ├── contracts/
│   └── generator/
├── infra/                          # Terraform — phase 2 (placeholder README only)
├── adf/                            # ADF pipelines — phase 2 (placeholder README only)
└── resources/                      # Databricks Asset Bundle YAML — phase 2 (placeholder README only)
```

`data/` (git-ignored) holds generated output:

```
data/
├── landing/                        # exactly what source systems would deliver
├── _expected/                      # answer keys and injection logs — TEST ONLY, never read by the pipeline
└── _state/state.json               # generator state between runs
```

---

## 3. Branching, PRs and tickets

- **Trunk-based:** `main` is always releasable. Short-lived branches named `feature/HDP-<n>-<short-desc>`, `fix/HDP-<n>-...` or `chore/HDP-<n>-...`.
- **Tickets:** GitHub Issues act as Jira. Issue titles start with `HDP-<n>`; a GitHub Project board has columns To do, In progress, In review, Done.
- **Commits** start with the ticket key: `HDP-2: add sap_date helper and tests`.
- **Merging:** squash merge only; the branch is deleted after merge.
- **PR template** (`.github/pull_request_template.md`): What changed · Why (ticket) · How it was tested · Data or contract changes · Risks and rollback · Screenshots or sample output.
- **CODEOWNERS:** the owner (`@<owner-github-username>`) owns everything; `contracts/` and `src/halvern/common/` are called out explicitly, because later they become shared code that needs extra review.

---

## 4. CI workflow (`.github/workflows/ci.yml`)

Triggers: `pull_request` to `main`, and `push` to `main`.

| Job | Steps | Fails when |
| --- | --- | --- |
| `lint` | checkout → setup-python 3.12 → `pip install ruff` → `ruff check .` → `ruff format --check .` | Any lint or format error |
| `test` | checkout → setup-java (Temurin 17) → setup-python 3.12 with pip cache → `pip install -r requirements-dev.txt` → `pytest -m "not integration" --cov=src/halvern --cov=generator/halvern_gen --cov-report=term-missing --cov-fail-under=70` | Any failing test, or coverage below 70% |
| `generator-smoke` (added in PR 5) | install → `halvern-gen init --seed 7 --profile realistic --start 2026-07-01 --days 14 --scale tiny` → `halvern-gen day --date 2026-07-15` → `python -m halvern.contracts.validate_folder data/landing --contracts contracts --report data/_reports/validation.json` → `python -m halvern_gen.answer_key.check_injections data/_expected data/_reports/validation.json` | Validator crashes, or injected issues are not detected at the expected counts |

Upload `data/_reports/` and the coverage report as workflow artifacts. Job names must stay exactly `lint`, `test` and `generator-smoke`, because branch protection will require them.

---

## 5. The data generator

### 5.1 What it simulates

A pharma company with:

| Source system | Company codes (local) | Group code | Currency | Notes |
| --- | --- | --- | --- | --- |
| `PS4` (SAP S/4HANA) | 1000 US, 2000 DE, 2300 UK | same | USD, EUR, GBP | Main system |
| `JE1` (SAP ECC, Japan) | **1000** | **4000** | JPY | Same local code as the US: the clash is deliberate |

Mapping lives in `reference/company_code_map.csv`: `source_system, local_company_code, group_company_code, country, local_currency`.

### 5.2 Scale presets

| Preset | SKUs | Sold-to customers | Billing lines per day | Wholesaler 867 rows per week, each |
| --- | --- | --- | --- | --- |
| `tiny` (CI) | 40 | 60 | ~150 | ~300 |
| `small` (default) | 200 | 300 | ~1,500 | ~3,000 |
| `medium` | 1,000 | 1,500 | ~15,000 | ~30,000 |

### 5.3 Commands

```
halvern-gen init  --seed 42 --profile realistic --start 2026-07-01 --days 90 --scale small --out data
halvern-gen day   --date 2026-09-29 --out data          # one day's deltas and any files due that day
halvern-gen range --from 2026-09-29 --to 2026-10-05 --out data
```

- `init` writes full loads of master data, 90 days of billing history as one initial extract per object (`_op = I`), FX history, reference files and wholesaler weeks for the period, then saves state.
- `day` continues from `data/_state/state.json`: document number counters, last date, scheduled master-data changes, pending late records, pending resends.
- **Determinism is mandatory:** the same seed and the same sequence of commands produce byte-identical files. Seed every random stream from `(seed, date, source, object)`.

### 5.4 Landing layout and file names

```
data/landing/
├── sap/PS4/KNA1/load_date=2026-09-29/KNA1_20260929T010512Z_PS4_000123.csv
├── sap/PS4/KNVV/...
├── sap/PS4/MARA/...
├── sap/PS4/MAKT/...
├── sap/PS4/VBRK/...
├── sap/PS4/VBRP/...
├── sap/PS4/TCURR/...
├── sap/JE1/VBRK/... and VBRP/...           # Japan billing only
├── wholesaler/northline/867/week_end=2026-09-27/NL_867_20260927.csv
├── wholesaler/pacifica/867/week_end=2026-09-27/PHS867_20260927.dat
├── wholesaler/crestway/867/week_end=2026-09-27/CW_SALES_092726.csv
└── reference/wholesaler_item_xref/load_date=.../xref_20260929.csv
```

SAP file name: `<OBJECT>_<extract timestamp UTC>_<system>_<extract id, 6 digits>.csv`.

### 5.5 SAP extract format (all SAP objects)

- CSV, UTF-8, header row, comma delimiter, double-quote quoting, `\n` line endings.
- **Every field is text, exactly as SAP formats it:** keys zero-padded (MATNR 18, KUNNR 10, VBELN 10, POSNR 6); dates `YYYYMMDD`, with `00000000` meaning empty; amounts with `.` as decimal separator and no thousands separator; flags `X` or empty.
- Technical columns on every row, as the extraction layer adds them:

| Column | Meaning |
| --- | --- |
| `_op` | `I` insert, `U` update (after image, full row), `D` delete (key columns filled, others may be empty) |
| `_change_ts` | When the change happened in SAP, UTC, ISO 8601 |
| `_seq` | Increasing sequence within an extract; orders changes to the same key |
| `_extract_id` | Extract run ID, same for every row in the file |
| `_source_system` | `PS4` or `JE1` |

### 5.6 SAP objects and columns

| Object | Business meaning | Columns (besides technical) | Primary key |
| --- | --- | --- | --- |
| KNA1 | Customer general data | KUNNR, NAME1, LAND1, ORT01, PSTLZ, KTOKD, LOEVM | KUNNR |
| KNVV | Customer per sales area | KUNNR, VKORG, VTWEG, SPART, BZIRK, KDGRP, VKBUR | KUNNR, VKORG, VTWEG, SPART |
| MARA | Item general data | MATNR, MTART, MEINS, PRDHA, ZZ_NDC, LVORM | MATNR |
| MAKT | Item text | MATNR, SPRAS, MAKTX | MATNR, SPRAS |
| VBRK | Billing header | VBELN, FKART, FKDAT, BUKRS, VKORG, VTWEG, SPART, KUNAG, KUNRG, WAERK, NETWR, FKSTO, SFAKN, RFBSK, ERDAT | VBELN |
| VBRP | Billing item | VBELN, POSNR, MATNR, CHARG, FKIMG, VRKME, NETWR, WAVWR, PRCTR, WERKS, AUBEL, VGBEL | VBELN, POSNR |
| TCURR | Exchange rates | KURST, FCURR, TCURR, GDATU, UKURS, FFACT, TFACT | KURST, FCURR, TCURR, GDATU |

Business rules the generator must follow:

- **Billing types (FKART):** F2 invoice, L2 debit memo, G2 credit memo, RE returns credit, S1 cancellation, IV intercompany invoice (PS4 company 2000 billing PS4 company 1000 as customer `0000090001`). NETWR and FKIMG are **always positive**; the sign comes from FKART.
- **Cancellations:** an S1 document has `SFAKN` = the cancelled VBELN; the original gets `FKSTO = X` through a `U` row in a later extract.
- **Posting status:** new invoices may start with `RFBSK = A` (not yet in accounting) and change to `C` the next day through a `U` row; a few stay at `B` (error).
- **JE1 amounts:** JPY is stored with two decimals, as SAP does: a real ¥1,000 is written `10.00`.
- **TCURR:** `GDATU` is stored as `99999999 − YYYYMMDD`, as text. Rate types: `M` (daily) and `ZAVG` (monthly average, valid from the first of the month). For EUR→USD and JPY→USD, `UKURS` is a direct quote; **GBP rates are stored as indirect quotes with a negative UKURS** (rate = 1 / |UKURS|), as SAP does. JPY uses factor `FFACT = 100` (rate per 100 JPY).
- **Item hierarchy:** `PRDHA` is 18 characters: business unit (5) + therapy area (5) + brand (8). About 4 business units, 8 therapy areas, 12 brands at `small` scale. US items carry an 11-digit `ZZ_NDC`; non-US items leave it empty.
- **Master data changes:** customers change sales district (`BZIRK`) or customer group; items move brand (`PRDHA` changes). Each change is a `U` row. Some changes are scheduled to happen **twice on the same day** for one key (an SCD2 trap).
- **Deletes:** only for KNVV (a customer removed from a sales area) and rarely MAKT texts. Billing documents are never deleted.

### 5.7 Wholesaler 867 files (weekly sales by wholesalers to hospitals and pharmacies)

| Wholesaler | Arrives | Format | Product code | Quantity unit | Quirks |
| --- | --- | --- | --- | --- | --- |
| Northline | Monday | CSV, comma, header | NDC-11, no dashes | Cartons | Corrected week resent as `..._v2.csv` |
| Pacifica | Tuesday | Fixed-width `.dat`, no header (positions below) | NDC-10 with dashes | Eaches (vials) | Negative quantity: minus sign in position 55 |
| Crestway | Wednesday to Friday (2–3 days late) | CSV, semicolon, header | Crestway's own item number | Cases of 10 | Dates `MM/DD/YYYY`; some customer names `CONFIDENTIAL`; resends **without** `_v2` |

Northline columns: `report_week_end, dc_id, ndc11, cust_hin, cust_name, cust_zip, qty, uom, contract_id, invoice_no, invoice_date`.

Pacifica positions (1-based, inclusive): 1–3 sender `PHS` · 4–11 week end `YYYYMMDD` · 12–14 DC · 15–27 NDC-10 with dashes, left-aligned, space-padded · 28–35 quantity, zero-padded · 36–37 unit `EA` · 38–45 customer number · 46–54 DEA number · 55 sign (space or `-`).

Crestway columns: `WEEK_END;DC;CW_ITEM;CUSTOMER;ZIP;QTY_CS;EXT_COST`.

`reference/wholesaler_item_xref`: `wholesaler, wholesaler_item, ndc11, halvern_item, valid_from, valid_to` (full file on each change).

Wholesaler sales are generated from Halvern's sell-in to US wholesaler customers, with a stock lag, so sell-in and sell-out are realistic but never equal.

### 5.8 Mess switches (profiles)

Each profile YAML sets rates or counts for the injections below. `clean` sets all to zero (only inherent SAP formats remain); `chaos` is about 10× `realistic`.

| Injection | Where | `realistic` setting | What the pipeline must later do |
| --- | --- | --- | --- |
| `duplicate_file` | Any source | 2% of files delivered twice, same bytes, sometimes a new name | Skip by content fingerprint |
| `duplicate_row` | SAP | 0.5% of rows repeated within a file | Drop exact duplicates, count them |
| `key_collision` | SAP | 0.2%: same key twice in one file with different values and `_seq` | Keep the highest `_seq` |
| `null_key` | SAP, wholesalers | 0.2% of rows with blank key fields | Quarantine: `missing_key` |
| `bad_type` | SAP, wholesalers | 0.2%: quantity `N/A`, date `20261345` | Quarantine: `bad_type` |
| `late_arrival` | VBRK/VBRP | 3% of a day's documents delivered 1–3 days later | Count by business date (FKDAT), not arrival date |
| `out_of_order` | KNA1/KNVV | 0.5%: `U` before its `I` within a file (by row position, correct by `_seq`) | Order by `_seq`, not file position |
| `same_day_double_change` | KNVV, MARA | 2 events per month | SCD2 must keep the last change of the day |
| `unknown_wholesaler_item` | Crestway, Pacifica | 1% of rows | Quarantine: `unknown_item` until mapped |
| `corrected_resend` | Wholesalers | 1 per month per wholesaler | Replace by wholesaler + DC + week |
| `schema_drift` | VBRP | On day 30 of the run, column `ZZ_CONTRACT` is added at the end | Accept and flag if contract allows new columns |
| `corrupt_file` | Any | 1 per month: last line truncated | Reject the whole file |
| `empty_file` | Any | 1 per month: header only | Reject or accept per contract `allow_empty` |
| `fx_gap` | TCURR | 1 per quarter: a ZAVG month missing for one currency | Later: fall back to last rate and flag |
| `latin1_encoding` | Crestway | 1 file per quarter in Latin-1 with `Müller` | Reject: `encoding_error` |

Every injection is written to `data/_expected/<date>/injections.json` with: injection type, source, file, row number(s), business key(s), details.

### 5.9 Answer key (the test oracle)

The generator knows the truth, so it writes `data/_expected/answer_key.json` after every run, recalculated over all generated days:

- **Billing truth per group company code × FKDAT:** gross invoiced (F2 + L2), credits (G2 + RE), cancellations (S1), intercompany (IV), net billed (signed sum excluding cancelled pairs correctly), units (signed FKIMG); in **document currency**, **local currency** (JPY as real yen, not SAP's two-decimal form) and **USD at the ZAVG rate of the FKDAT month**.
- **Sell-out truth per wholesaler × week × Halvern item:** cartons (after unit conversion) and dollar value.
- **Expected data-quality counts:** per object, the number of rows each injection should cause to be dropped, quarantined or flagged.

Later phases reconcile silver and gold against this key: if the pipeline's net sales differ from the answer key, the pipeline is wrong.

---

## 6. Data contracts

One YAML per source object in `contracts/`, for example `contracts/sap_vbrk.yaml`:

```yaml
name: sap_vbrk
version: 1
owner: sales-squad
source_system: [PS4, JE1]
landing_path: sap/{source_system}/VBRK/
format: csv
delimiter: ","
encoding: utf-8
header: true
allow_empty: false
allow_new_columns: true          # new columns are accepted and flagged as schema_drift
primary_key: [VBELN]
change_mode_column: _op
order_columns: [_change_ts, _seq]
business_date_column: FKDAT
arrival: daily by 01:30 UTC
columns:
  - {name: VBELN, type: string, required: true, pattern: "^[0-9]{10}$"}
  - {name: FKART, type: string, required: true, allowed: [F2, L2, G2, RE, S1, IV]}
  - {name: FKDAT, type: sap_date, required: true}
  - {name: BUKRS, type: string, required: true, pattern: "^[0-9]{4}$"}
  - {name: NETWR, type: decimal(18,2), required: true, min: 0}
  - {name: FKSTO, type: string, required: false, allowed: ["", "X"]}
  - {name: SFAKN, type: string, required: false, pattern: "^([0-9]{10})?$"}
  - {name: RFBSK, type: string, required: true, allowed: [A, B, C]}
  # ... every column in section 5.6, plus the technical columns
```

Contracts are needed for: KNA1, KNVV, MARA, MAKT, VBRK, VBRP, TCURR, Northline 867, Pacifica 867 (with a `positions` list instead of a delimiter), Crestway 867, and the wholesaler item cross-reference.

### 6.1 Validator (`src/halvern/contracts/`)

`load_contract(path) -> Contract` validates the YAML itself (unknown keys or types fail).

`validate_file(spark, file_path, contract) -> ValidationResult` with:

**File-level checks (any failure rejects the whole file):**

| Check | Reason code |
| --- | --- |
| File cannot be decoded with the contract encoding | `encoding_error` |
| Header is missing a required column | `missing_column` |
| Data row count is zero and `allow_empty: false` | `empty_file` |
| The last line has the wrong number of fields | `corrupt_file` |
| Fixed-width line length is wrong | `bad_record_length` |

**Row-level checks (bad rows go to quarantine, good rows continue):**

| Check | Reason code |
| --- | --- |
| Required field blank or null | `missing_key` (for key columns) or `missing_value` |
| Value cannot be cast to the contract type | `bad_type` |
| Pattern mismatch | `bad_format` |
| Value not in the allowed list | `bad_value` |
| Below min or above max | `out_of_range` |

**Duplicates inside one file:**
- Rows identical in every column: keep one, count the others as `duplicate_row` (not quarantined).
- Same primary key, different values: keep the row with the highest `(_change_ts, _seq)`, record the others as `key_collision` (not quarantined).

**New columns:** if `allow_new_columns` is true, extra columns are kept and the result carries a `schema_drift` warning listing them; if false, the file is rejected with `unexpected_column`.

`ValidationResult` contains: `status` (`accepted`, `accepted_with_warnings`, `rejected`), `reject_reason`, `row_count_in`, `row_count_valid`, `row_count_quarantined`, counts per reason code, `warnings`, the valid DataFrame, and the quarantine DataFrame (original columns plus `_reason_code`, `_reason_detail`, `_file_name`, `_row_number`).

`python -m halvern.contracts.validate_folder <landing> --contracts <dir> --report <json>` validates every file found, matches it to its contract by path, and writes a JSON report.

---

## 7. Core helper functions (`src/halvern/common/`)

All are pure, Spark Column or DataFrame functions unless noted, each with unit tests covering the listed cases.

| Function | Rule | Unit test cases |
| --- | --- | --- |
| `strip_sap_zeros(col)` | Remove leading zeros only when the value is all digits; all zeros become `0`; alphanumeric values unchanged; blank or null become null | `000000000000400123`→`400123`; `0000000000`→`0`; `ABC0012`→`ABC0012`; `''`→null |
| `sap_date(col)` | `YYYYMMDD` → date; `00000000` or blank → null; invalid → null | valid date; `00000000`; `20261345`; leap day `20280229` |
| `invert_gdatu(col)` | `99999999 − int(GDATU)` → `YYYYMMDD` → date | known pair 79739070 ↔ 20260929 |
| `currency_shift(amount, currency, decimals_map)` | Real amount = SAP amount × 10^(2 − decimals); default decimals 2 | JPY `10.00`→`1000`; EUR unchanged; a 3-decimal currency divided by 10 |
| `sap_rate(ukurs, ffact, tfact)` | Negative UKURS = indirect: rate = 1/|UKURS|; then rate × TFACT / FFACT gives units of TCURR per 1 unit of FCURR | direct EUR; indirect GBP; JPY with FFACT 100 |
| `billing_sign(fkart)` | +1 for F2, L2, IV; −1 for G2, RE, S1; unknown → null | each type; unknown |
| `ndc10_to_ndc11(ndc10)` | Input with dashes: 4-4-2 → pad labeler; 5-3-2 → pad product; 5-4-1 → pad package; returns 11 digits; without dashes → null (ambiguous) | one per form; no dashes; garbage |
| `dedupe_latest(df, keys, order_cols)` | Keep one row per key with the highest order columns (window row_number) | ties broken by `_seq`; null keys excluded |
| `row_hash(df, cols)` | SHA-256 of the columns joined with a fixed separator, nulls as `\u0000`; used later for SCD2 change detection | null vs empty string differ; column order matters |
| `file_fingerprint(path)` (plain Python) | SHA-256 of the file bytes, read in chunks | same bytes same hash; renamed file same hash |

`tests/conftest.py` creates one session-scoped SparkSession: `master("local[2]")`, `spark.sql.shuffle.partitions=2`, `spark.sql.session.timeZone=UTC`, UI disabled.

---

## 8. Generator tests (`tests/generator/`)

1. **Determinism:** run `init` (tiny, 7 days) and `day` twice into two folders with the same seed; every file hash matches.
2. **Answer key arithmetic:** recompute net billed per company and day directly from the generated files with the helper functions; it must equal the answer key.
3. **Injection rates:** with the `chaos` profile, each injection type appears at least once, and its logged count matches what is in the files.
4. **Clean profile:** with `clean`, the validator reports zero quarantined rows and zero rejected files.
5. **Formats:** Pacifica lines are exactly 55 characters; SAP keys have the right padded lengths; GDATU is inverted.

---

## 9. Definition of done for spec 01

- `main` has passing `lint`, `test` and `generator-smoke` checks.
- Coverage of `src/halvern` and `generator/halvern_gen` is at least 70%.
- `halvern-gen init` (small) produces 90 days of landing files in under 2 minutes in the Claude Code environment.
- The validation report shows quarantine counts by reason that match `injections.json`.
- README explains: what the project is, how to generate data, how to run tests, the branching rules, and the mess profiles.

---

## 10. Pull request plan

| PR | Ticket | Contents | Owner checks after merge |
| --- | --- | --- | --- |
| 1 | HDP-1 | Skeleton: layout, `pyproject.toml`, `requirements-dev.txt`, `.gitignore`, ruff and pytest config, CI with `lint` and `test` (one trivial test), PR template, CODEOWNERS, README, placeholder READMEs in `infra/`, `adf/`, `resources/` | CI green; then set branch protection (section 11) |
| 2 | HDP-2 | Section 7 helper functions and unit tests | All unit tests pass; coverage report visible |
| 3 | HDP-3 | Section 6 contracts for every object, loader, validator, `validate_folder`, contract tests (hand-made small files for every reason code) | Each reason code has a test |
| 4 | HDP-4 | Section 5 generator: master data, billing (PS4 and JE1), TCURR, wholesalers, cross-reference, mess injections, answer key, state, CLI, generator tests | `halvern-gen init` works locally |
| 5 | HDP-5 | `generator-smoke` CI job, `check_injections`, artifacts upload, README usage, `docs/failure-lab.md` with exercises FL-01 to FL-04 (section 12) | All three CI jobs green |

---

## 11. Repository settings (the owner does these in GitHub, after PR 1)

1. **Settings → General → Pull Requests:** allow squash merging only; automatically delete head branches.
2. **Settings → Rules → Rulesets → New branch ruleset** for `main`: require a pull request before merging (0 approvals, since this is a one-person repo); require status checks `lint` and `test` (add `generator-smoke` after PR 5); block force pushes; require linear history.
3. **Issues:** create HDP-1 to HDP-5 matching section 10; create a Project board with To do, In progress, In review, Done.

---

## 12. Failure lab exercises for phase 1 (`docs/failure-lab.md`)

| ID | Do this | You should see | Learn |
| --- | --- | --- | --- |
| FL-01 | On a branch, change `billing_sign` so S1 returns +1; push and open a PR | `test` fails on the S1 case; the merge button is blocked | How CI protects `main` |
| FL-02 | Branch A adds a column to `contracts/sap_vbrk.yaml`; branch B changes the type of the line next to it; merge A, then try B | A merge conflict on B | Resolving conflicts, re-running CI |
| FL-03 | Replace one seeded random call in the generator with an unseeded one | The determinism test fails | Why reproducible test data matters |
| FL-04 | Generate with `--profile chaos`, run `validate_folder` | Quarantine counts by reason, a rejected corrupt file, a schema-drift warning | What real messy data looks like before silver |
