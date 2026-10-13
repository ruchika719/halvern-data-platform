"""Validate one landing file (or one SAP run folder) against its contract."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from halvern.contracts import checks, readers
from halvern.contracts import model as m

ACCEPTED = "accepted"
ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
REJECTED = "rejected"


@dataclass
class ValidationResult:
    file_path: str
    contract: str
    status: str
    reject_reason: str | None = None
    reject_detail: str | None = None
    row_count_in: int = 0
    row_count_valid: int = 0
    row_count_quarantined: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    valid_df: DataFrame | None = field(default=None, repr=False)
    quarantine_df: DataFrame | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Everything except the DataFrames, for the JSON report."""
        return {
            "file_path": self.file_path,
            "contract": self.contract,
            "status": self.status,
            "reject_reason": self.reject_reason,
            "reject_detail": self.reject_detail,
            "row_count_in": self.row_count_in,
            "row_count_valid": self.row_count_valid,
            "row_count_quarantined": self.row_count_quarantined,
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "warnings": self.warnings,
        }


def rejected(file_path: str, contract: m.Contract, code: str, detail: str) -> ValidationResult:
    return ValidationResult(
        file_path=file_path,
        contract=contract.name,
        status=REJECTED,
        reject_reason=code,
        reject_detail=detail,
        reason_counts={code: 1},
    )


def validate_file(
    spark: SparkSession, file_path: str | Path, contract: m.Contract
) -> ValidationResult:
    """Run the file-level checks, then the row-level checks and in-file duplicate handling.

    For a Parquet contract, ``file_path`` is a run folder: ``.../<OBJECT>/<load_type>/<run_id>``.
    """
    path = Path(file_path)
    try:
        if contract.format == "parquet":
            loaded = readers.read_parquet_run(spark, path, contract)
        elif contract.format == "fixed_width":
            loaded = readers.read_fixed_width(spark, path, contract)
        else:
            loaded = readers.read_csv(spark, path, contract)
        if contract.control_file:
            readers.check_control_file(loaded.df, path, contract)
    except readers.FileRejected as exc:
        return rejected(str(path), contract, exc.code, exc.detail)

    drift = [c for c in loaded.file_columns if c not in contract.column_names]
    warnings = [{"code": m.SCHEMA_DRIFT, "columns": drift}] if drift else []

    annotated = checks.add_reasons(loaded.df, contract).cache()
    row_count_in = annotated.count()
    quarantine = annotated.where(F.col(checks.REASON_CODE).isNotNull()).drop(readers.PARSE_ERROR)
    good = annotated.where(F.col(checks.REASON_CODE).isNull()).drop(
        checks.REASON_CODE, checks.REASON_DETAIL, readers.PARSE_ERROR
    )

    reason_counts = {
        r[checks.REASON_CODE]: r["count"]
        for r in quarantine.groupBy(checks.REASON_CODE).count().collect()
    }
    row_count_quarantined = sum(reason_counts.values())

    unique, copies = checks.drop_exact_duplicates(good, loaded.file_columns)
    duplicate_rows = copies.count()
    unique = unique.cache()
    before_keys = unique.count()
    valid = checks.keep_latest_per_key(unique, contract)
    row_count_valid = valid.count()
    key_collisions = before_keys - row_count_valid
    if duplicate_rows:
        reason_counts[m.DUPLICATE_ROW] = duplicate_rows
    if key_collisions:
        reason_counts[m.KEY_COLLISION] = key_collisions

    return ValidationResult(
        file_path=str(path),
        contract=contract.name,
        status=ACCEPTED_WITH_WARNINGS if warnings else ACCEPTED,
        row_count_in=row_count_in,
        row_count_valid=row_count_valid,
        row_count_quarantined=row_count_quarantined,
        reason_counts=reason_counts,
        warnings=warnings,
        valid_df=valid,
        quarantine_df=quarantine,
    )
