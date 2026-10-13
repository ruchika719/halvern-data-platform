"""Read landing files into Spark DataFrames and run the file-level checks.

Reading happens once per file in plain Python (decoding, splitting lines, the task log and the
control file). Every row-level rule runs later as Spark expressions in ``checks.py``.
"""

import csv
import io
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

from halvern.common import file_fingerprint
from halvern.contracts import model as m

ROW_NUMBER = "_row_number"
FILE_NAME = "_file_name"
PARSE_ERROR = "_parse_error"
TECHNICAL = (ROW_NUMBER, FILE_NAME, PARSE_ERROR)


class FileRejected(Exception):
    """A file-level check failed; the whole file or run is rejected."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class LoadedFile:
    df: DataFrame
    file_columns: list[str]  # columns as delivered, in delivery order


def _string_frame(
    spark: SparkSession, columns: list[str], rows: list[tuple], file_name: str
) -> DataFrame:
    schema = StructType(
        [StructField(c, StringType()) for c in columns]
        + [
            StructField(ROW_NUMBER, IntegerType(), False),
            StructField(PARSE_ERROR, StringType()),
        ]
    )
    return spark.createDataFrame(rows, schema).withColumn(FILE_NAME, F.lit(file_name))


def _decode(path: Path, contract: m.Contract) -> str:
    data = path.read_bytes()
    try:
        return data.decode(contract.encoding)
    except UnicodeDecodeError as exc:
        raise FileRejected(
            m.ENCODING_ERROR, f"not valid {contract.encoding} at byte {exc.start}"
        ) from exc


def check_header(contract: m.Contract, file_columns: list[str]) -> list[str]:
    """Reject on missing required or unexpected columns; return drifted column names."""
    missing = [c for c in contract.required_columns if c not in file_columns]
    if missing:
        raise FileRejected(m.MISSING_COLUMN, ", ".join(missing))
    extra = [c for c in file_columns if c not in contract.column_names]
    if extra and not contract.allow_new_columns:
        raise FileRejected(m.UNEXPECTED_COLUMN, ", ".join(extra))
    return extra


def _check_not_empty(contract: m.Contract, row_count: int) -> None:
    if row_count == 0 and not contract.allow_empty:
        raise FileRejected(m.EMPTY_FILE, "no data rows")


def read_csv(spark: SparkSession, path: Path, contract: m.Contract) -> LoadedFile:
    text = _decode(path, contract)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=contract.delimiter, quotechar='"')
    try:
        records = [r for r in reader if r]
    except csv.Error as exc:
        raise FileRejected(m.CORRUPT_FILE, f"cannot parse CSV: {exc}") from exc
    if contract.header:
        if not records:
            raise FileRejected(m.MISSING_COLUMN, "file has no header")
        columns, records = records[0], records[1:]
    else:
        columns = list(contract.column_names)
    check_header(contract, columns)
    _check_not_empty(contract, len(records))
    width = len(columns)
    if records and len(records[-1]) != width:
        raise FileRejected(
            m.CORRUPT_FILE, f"last line has {len(records[-1])} fields, expected {width}"
        )
    rows = []
    for number, record in enumerate(records, start=1):
        error = None
        if len(record) != width:
            error = f"line has {len(record)} fields, expected {width}"
            record = (record + [None] * width)[:width]
        rows.append((*record, number, error))
    return LoadedFile(_string_frame(spark, columns, rows, str(path)), columns)


def read_fixed_width(spark: SparkSession, path: Path, contract: m.Contract) -> LoadedFile:
    text = _decode(path, contract)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    _check_not_empty(contract, len(lines))
    for number, line in enumerate(lines, start=1):
        if len(line) != contract.record_length:
            raise FileRejected(
                m.BAD_RECORD_LENGTH,
                f"line {number} has {len(line)} characters, expected {contract.record_length}",
            )
    columns = [p.name for p in contract.positions]
    rows = [
        (*[line[p.start - 1 : p.end].strip() for p in contract.positions], number, None)
        for number, line in enumerate(lines, start=1)
    ]
    return LoadedFile(_string_frame(spark, columns, rows, str(path)), columns)


def read_task_log(run_folder: Path) -> tuple[Path, dict | None]:
    """Find and read the task log for ``<SYSTEM>/<OBJECT>/<load_type>/<run_id>/``."""
    system_folder = run_folder.parent.parent.parent
    log_path = system_folder / "_tasklog" / f"{run_folder.name}.json"
    if not log_path.is_file():
        return log_path, None
    try:
        return log_path, json.loads(log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return log_path, {}


def read_parquet_run(spark: SparkSession, run_folder: Path, contract: m.Contract) -> LoadedFile:
    """Read one SAP replication run folder after checking it against its task log."""
    object_name = run_folder.parent.parent.name
    log_path, log = read_task_log(run_folder)
    if log is None:
        raise FileRejected(m.INCOMPLETE_RUN, f"task log not found: {log_path}")
    status = log.get("status")
    if status == "FAILED":
        raise FileRejected(m.FAILED_RUN, f"run {run_folder.name} has status FAILED")
    if status != "COMPLETED":
        raise FileRejected(m.INCOMPLETE_RUN, f"run status is {status!r}, not COMPLETED")
    entry = next((o for o in log.get("objects", []) if o.get("object") == object_name), None)
    if entry is None:
        raise FileRejected(m.INCOMPLETE_RUN, f"task log has no entry for {object_name}")

    parts = sorted(run_folder.glob("part-*.parquet"))
    if len(parts) != entry.get("part_files"):
        raise FileRejected(
            m.INCOMPLETE_RUN,
            f"{len(parts)} part file(s) found, task log says {entry.get('part_files')}",
        )
    if not parts:
        expected_rows = entry.get("rows", 0)
        if expected_rows:
            raise FileRejected(m.INCOMPLETE_RUN, f"no part files, task log says {expected_rows}")
        _check_not_empty(contract, 0)
        return LoadedFile(
            _string_frame(spark, list(contract.column_names), [], str(run_folder)),
            list(contract.column_names),
        )

    try:
        df = spark.read.parquet(*[str(p) for p in parts])
        row_count = df.count()
    except Exception as exc:  # Spark raises several error types for unreadable Parquet
        raise FileRejected(m.CORRUPT_FILE, f"cannot read Parquet: {exc}".splitlines()[0]) from exc
    columns = df.columns
    check_header(contract, columns)
    if row_count != entry.get("rows"):
        raise FileRejected(
            m.INCOMPLETE_RUN, f"{row_count} row(s) found, task log says {entry.get('rows')}"
        )
    _check_not_empty(contract, row_count)

    # Row number within each part file; Spark reads a small part file in order.
    file_name = F.regexp_replace(F.input_file_name(), "^file:", "")
    order = Window.partitionBy(FILE_NAME).orderBy(F.monotonically_increasing_id())
    df = (
        df.withColumn(FILE_NAME, file_name)
        .withColumn(ROW_NUMBER, F.row_number().over(order))
        .withColumn(PARSE_ERROR, F.lit(None).cast("string"))
    )
    return LoadedFile(df, columns)


def check_control_file(df: DataFrame, path: Path, contract: m.Contract) -> None:
    """Compare a partner file with its ``.ctl`` file: row count, total quantity, SHA-256."""
    ctl_path = path.with_name(path.name + ".ctl")
    if not ctl_path.is_file():
        raise FileRejected(m.CONTROL_MISMATCH, "control file missing")
    try:
        control = json.loads(ctl_path.read_text(encoding="utf-8"))
        expected_rows = int(control["row_count"])
        expected_qty = Decimal(str(control["total_qty"]))
        expected_sha = str(control["file_sha256"])
    except (ValueError, KeyError, TypeError, InvalidOperation, UnicodeDecodeError) as exc:
        raise FileRejected(m.CONTROL_MISMATCH, f"control file unreadable: {exc}") from exc

    actual_sha = file_fingerprint(path)
    if actual_sha != expected_sha:
        raise FileRejected(m.CONTROL_MISMATCH, "file_sha256 differs from the data file")

    qty = F.expr(f"try_cast(trim(`{contract.control_qty_column}`) AS DECIMAL(38,6))")
    if contract.control_qty_sign_column:
        qty = F.when(F.col(contract.control_qty_sign_column) == "-", -qty).otherwise(qty)
    totals = df.agg(F.count(F.lit(1)).alias("rows"), F.sum(qty).alias("qty")).first()
    if totals["rows"] != expected_rows:
        raise FileRejected(
            m.CONTROL_MISMATCH,
            f"row_count {expected_rows} in control file, {totals['rows']} in data",
        )
    actual_qty = totals["qty"] if totals["qty"] is not None else Decimal(0)
    if actual_qty != expected_qty:
        raise FileRejected(
            m.CONTROL_MISMATCH, f"total_qty {expected_qty} in control file, {actual_qty} in data"
        )
