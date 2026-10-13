# Spec 01a — Change request HDP-6: realistic source formats

Raised after spec 01 was approved, before PR 3 (contracts) and PR 4 (generator) start. It changes how SAP data lands, so it is closer to what an SAP Datasphere replication flow writes into ADLS.

## Why

In the real platform, SAP data reaches the lake through SAP Datasphere replication flows (or the AWS Glue connector in the AWS design). Datasphere writes **Parquet** files to cloud storage, split into an initial load and then delta loads. CSV was a simplification, so it is replaced.

## Changes

### 1. SAP landing format (replaces spec 01 section 5.5, format part only)

- Format: **Parquet**, Snappy compression, one folder per object and run:
  `landing/sap/<SYSTEM>/<OBJECT>/initial/<run_id>/part-00000.parquet` for the initial load, and
  `landing/sap/<SYSTEM>/<OBJECT>/delta/<run_id>/part-0000N.parquet` for each delta run (a run may write several part files).
- Column types: **all business fields stay `string`**, holding SAP's internal formats (zero-padded keys, `YYYYMMDD` dates, `00000000` for empty, amounts as text). In a real Datasphere replication, some types arrive already converted; keeping text preserves the traps the pipeline must handle and that the contracts check.
- Technical columns are unchanged (`_op`, `_change_ts`, `_seq`, `_extract_id`, `_source_system`), with `_change_ts` as a Parquet timestamp in UTC.
- A run can be **partially written**: a `corrupt_file` injection for SAP now means a run folder with one part file missing. The run's task log (below) shows how many parts and rows there should be.

### 2. Run task log (new)

Every SAP run writes `landing/sap/<SYSTEM>/_tasklog/<run_id>.json`, like the task log a replication flow shows in its monitor:

```json
{"run_id": "PS4-20260929-0123", "system": "PS4", "load_type": "delta",
 "started_utc": "2026-09-29T01:05:12Z", "finished_utc": "2026-09-29T01:07:40Z",
 "objects": [{"object": "VBRK", "part_files": 2, "rows": 1534},
             {"object": "VBRP", "part_files": 3, "rows": 4410}],
 "status": "COMPLETED"}
```

Some runs end with `"status": "FAILED"` and no files for one object (a new injection, `failed_run`, once a month in `realistic`). The ingestion layer must not treat a failed run as "no changes".

### 3. Control files for partner files (new)

Each wholesaler file is followed by a control file with the same name plus `.ctl`, containing `row_count`, `total_qty` and `file_sha256`. Injection `control_mismatch` (once a month in `realistic`): the control file disagrees with the data file. The file must be rejected with reason `control_mismatch`.

### 4. Oracle (Italy) source: moved to phase 2

The Oracle EBS source will be simulated as an **Azure SQL Database** (free offer) holding Oracle-like tables, with inserts, updates and deletes applied by a small script each simulated day. It is read with ADF incremental copy (watermark and config table), so the generator does not write Oracle files in phase 1.

### 5. Contracts and validator

- `format: parquet` is added; for Parquet contracts, file-level checks become: required columns present, part-file count and row count match the task log, and run status is `COMPLETED`. New reason codes: `incomplete_run`, `failed_run`, `control_mismatch`.
- Row-level checks are unchanged (values are still text).

### 6. Answer key and injections

`answer_key.json` and `injections.json` cover the new injections `failed_run`, `control_mismatch` and the SAP partial run.

## Impact

PR 3 and PR 4 implement this change request together with spec 01. PR 1 and PR 2 are unaffected.
