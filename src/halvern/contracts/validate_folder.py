"""Validate every file in a landing folder and write a JSON report.

Usage::

    python -m halvern.contracts.validate_folder data/landing --contracts contracts \\
        --report data/_reports/validation.json
"""

import argparse
import fnmatch
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql import SparkSession

from halvern.contracts import model as m
from halvern.contracts.validator import REJECTED, validate_file

_PARQUET_TAIL = r"(?P<load_type>initial|delta)/(?P<run_id>[^/]+)/part-[0-9]+\.parquet"


def _path_regex(contract: m.Contract) -> re.Pattern:
    prefix = re.escape(contract.landing_path).replace(
        re.escape("{source_system}"), "(?P<source_system>[^/]+)"
    )
    if contract.format == "parquet":
        return re.compile(f"^{prefix}{_PARQUET_TAIL}$")
    name = fnmatch.translate(contract.file_pattern or "*").removeprefix("(?s:").removesuffix(")\\Z")
    return re.compile(f"^{prefix}(?:[^/]+/)*{name}$")


def match_contract(rel_path: str, contracts: list[m.Contract]) -> m.Contract | None:
    """The contract whose landing path and file pattern match a path relative to landing."""
    for contract in contracts:
        match = _path_regex(contract).match(rel_path)
        if not match:
            continue
        system = match.groupdict().get("source_system")
        if system is not None and system not in contract.source_system:
            continue
        return contract
    return None


def discover(landing: Path, contracts: list[m.Contract]) -> tuple[dict[Path, m.Contract], list]:
    """Map each validation unit (file, or SAP run folder) to its contract."""
    units: dict[Path, m.Contract] = {}
    unmatched = []
    for path in sorted(p for p in landing.rglob("*") if p.is_file()):
        rel = path.relative_to(landing).as_posix()
        if path.name.endswith(".ctl") or "/_tasklog/" in f"/{rel}":
            continue
        contract = match_contract(rel, contracts)
        if contract is None:
            unmatched.append(rel)
        elif contract.format == "parquet":
            units[path.parent] = contract
        else:
            units[path] = contract
    return units, unmatched


def missing_run_objects(
    landing: Path, contracts: list[m.Contract], found: set[Path]
) -> list[dict[str, Any]]:
    """Entries for objects a task log lists but that have no run folder at all."""
    entries = []
    for log_path in sorted(landing.glob("sap/*/_tasklog/*.json")):
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        system = log_path.parent.parent.name
        run_id = log.get("run_id", log_path.stem)
        load_type = log.get("load_type", "delta")
        for obj in log.get("objects", []):
            folder = landing / "sap" / system / obj.get("object", "?") / load_type / run_id
            if folder in found:
                continue
            rel = (folder / "part-00000.parquet").relative_to(landing).as_posix()
            contract = match_contract(rel, contracts)
            failed = log.get("status") == "FAILED"
            code = m.FAILED_RUN if failed else m.INCOMPLETE_RUN
            entries.append(
                {
                    "file_path": str(folder),
                    "contract": contract.name if contract else None,
                    "status": REJECTED,
                    "reject_reason": code,
                    "reject_detail": f"no files for {obj.get('object')} in run {run_id}",
                    "row_count_in": 0,
                    "row_count_valid": 0,
                    "row_count_quarantined": 0,
                    "reason_counts": {code: 1},
                    "warnings": [],
                }
            )
    return entries


def validate_landing(
    spark: SparkSession, landing: Path, contracts: list[m.Contract]
) -> dict[str, Any]:
    units, unmatched = discover(landing, contracts)
    files = [validate_file(spark, path, contract).to_dict() for path, contract in units.items()]
    files += missing_run_objects(landing, contracts, set(units))

    statuses = Counter(f["status"] for f in files)
    reasons: Counter = Counter()
    for f in files:
        reasons.update(f["reason_counts"])
    by_contract: dict[str, Counter] = {}
    for f in files:
        by_contract.setdefault(f["contract"] or "unknown", Counter()).update(f["reason_counts"])
    return {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "landing": str(landing),
        "summary": {
            "files": len(files),
            "by_status": dict(sorted(statuses.items())),
            "reason_counts": dict(sorted(reasons.items())),
            "reason_counts_by_contract": {
                k: dict(sorted(v.items())) for k, v in sorted(by_contract.items())
            },
            "unmatched_files": len(unmatched),
        },
        "files": files,
        "unmatched_files": unmatched,
    }


def local_spark() -> SparkSession:
    return (
        SparkSession.builder.master("local[2]")
        .appName("halvern-validate-folder")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )


def main(argv: list[str] | None = None, spark: SparkSession | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("landing", type=Path, help="landing folder, such as data/landing")
    parser.add_argument("--contracts", type=Path, required=True, help="folder of contract YAML")
    parser.add_argument("--report", type=Path, required=True, help="JSON report to write")
    args = parser.parse_args(argv)

    contracts = m.load_contracts(args.contracts)
    report = validate_landing(spark or local_spark(), args.landing, contracts)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(
        f"Validated {summary['files']} file(s): {summary['by_status']}; "
        f"{summary['unmatched_files']} unmatched. Report: {args.report}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
