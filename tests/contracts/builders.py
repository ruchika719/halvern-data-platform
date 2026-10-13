"""Builders for small hand-made landing files used by the contract tests."""

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from halvern.common import file_fingerprint


def northline_row(**overrides):
    row = {
        "report_week_end": "2026-09-27",
        "dc_id": "DC01",
        "ndc11": "12345067890",
        "cust_hin": "AB1234567",
        "cust_name": "St Mary Hospital",
        "cust_zip": "10001",
        "qty": "5",
        "uom": "CT",
        "contract_id": "",
        "invoice_no": "INV0001",
        "invoice_date": "2026-09-25",
    }
    row.update(overrides)
    return row


def write_csv(path: Path, rows, *, header=None, delimiter=",", qty_column=None, ctl=True):
    """Write a CSV with ``\\n`` endings and, optionally, a matching control file."""
    header = header or list(rows[0].keys())
    lines = [delimiter.join(header)]
    lines += [delimiter.join(str(r.get(c, "")) for c in header) for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if ctl:
        write_ctl(path, rows, qty_column)
    return path


def write_ctl(path: Path, rows, qty_column, **overrides):
    total = Decimal(0)
    for r in rows:
        try:
            value = Decimal(str(r.get(qty_column, "")).strip())
        except InvalidOperation:  # non-numeric quantities are not part of the total
            continue
        total += -value if r.get("sign") == "-" else value
    control = {
        "row_count": len(rows),
        "total_qty": str(total),
        "file_sha256": file_fingerprint(path),
    }
    control.update(overrides)
    path.with_name(path.name + ".ctl").write_text(json.dumps(control), encoding="utf-8")


PACIFICA_WIDTHS = [
    ("sender", 3),
    ("week_end", 8),
    ("dc", 3),
    ("ndc10", 13),
    ("quantity", 8),
    ("unit", 2),
    ("customer_no", 8),
    ("dea_no", 9),
    ("sign", 1),
]


def pacifica_row(**overrides):
    row = {
        "sender": "PHS",
        "week_end": "20260927",
        "dc": "D01",
        "ndc10": "12345-678-90",
        "quantity": "00000012",
        "unit": "EA",
        "customer_no": "00001234",
        "dea_no": "AB1234567",
        "sign": " ",
    }
    row.update(overrides)
    return row


def pacifica_line(row) -> str:
    return "".join(str(row[name]).ljust(width)[:width] for name, width in PACIFICA_WIDTHS)


def write_pacifica(path: Path, rows, *, lines=None, ctl=True):
    lines = lines if lines is not None else [pacifica_line(r) for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    if ctl:
        write_ctl(path, rows, "quantity")
    return path


def vbrk_row(**overrides):
    row = {
        "VBELN": "0090000001",
        "FKART": "F2",
        "FKDAT": "20260929",
        "BUKRS": "1000",
        "VKORG": "1000",
        "VTWEG": "10",
        "SPART": "00",
        "KUNAG": "0000100001",
        "KUNRG": "0000100001",
        "WAERK": "USD",
        "NETWR": "1500.00",
        "FKSTO": "",
        "SFAKN": "",
        "RFBSK": "C",
        "ERDAT": "20260929",
        "_op": "I",
        "_change_ts": datetime(2026, 9, 29, 1, 0, tzinfo=UTC),
        "_seq": 1,
        "_extract_id": "PS4-20260929-0001",
        "_source_system": "PS4",
    }
    row.update(overrides)
    return row


def _arrow_type(name):
    if name == "_change_ts":
        return pa.timestamp("us", tz="UTC")
    if name == "_seq":
        return pa.int64()
    return pa.string()


def write_run(
    landing: Path,
    parts,
    *,
    system="PS4",
    obj="VBRK",
    run_id="PS4-20260929-0001",
    load_type="delta",
    status="COMPLETED",
    log_parts=None,
    log_rows=None,
    write_log=True,
    other_objects=(),
):
    """Write a run folder of Parquet part files plus its task log. Returns the run folder."""
    folder = landing / "sap" / system / obj / load_type / run_id
    folder.mkdir(parents=True, exist_ok=True)
    for i, rows in enumerate(parts):
        columns = list(rows[0].keys()) if rows else list(vbrk_row().keys())
        table = pa.table({c: pa.array([r.get(c) for r in rows], _arrow_type(c)) for c in columns})
        pq.write_table(table, folder / f"part-{i:05d}.parquet", compression="snappy")
    if write_log:
        objects = [
            {
                "object": obj,
                "part_files": len(parts) if log_parts is None else log_parts,
                "rows": sum(len(p) for p in parts) if log_rows is None else log_rows,
            },
            *other_objects,
        ]
        log = {
            "run_id": run_id,
            "system": system,
            "load_type": load_type,
            "started_utc": "2026-09-29T01:05:12Z",
            "finished_utc": "2026-09-29T01:07:40Z",
            "objects": objects,
            "status": status,
        }
        log_dir = landing / "sap" / system / "_tasklog"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{run_id}.json").write_text(json.dumps(log), encoding="utf-8")
    return folder
