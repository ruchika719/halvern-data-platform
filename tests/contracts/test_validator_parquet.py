"""validate_file on SAP Parquet run folders checked against their task logs."""

import json
from datetime import UTC, datetime

import pytest
from builders import vbrk_row, write_run

from halvern.contracts import validate_file

pytestmark = pytest.mark.contract


@pytest.fixture
def vbrk(contracts):
    return contracts["sap_vbrk"]


def docs(n, start=1):
    return [vbrk_row(VBELN=f"{90000000 + i:010d}", _seq=i) for i in range(start, start + n)]


def test_clean_run_with_two_parts(spark, tmp_path, vbrk):
    folder = write_run(tmp_path, [docs(3), docs(2, start=4)])
    result = validate_file(spark, folder, vbrk)
    assert result.status == "accepted"
    assert (result.row_count_in, result.row_count_valid) == (5, 5)
    names = {r._file_name.rsplit("/", 1)[-1] for r in result.valid_df.collect()}
    assert names == {"part-00000.parquet", "part-00001.parquet"}
    assert sorted(r._row_number for r in result.valid_df.collect()) == [1, 1, 2, 2, 3]


def test_values_stay_text(spark, tmp_path, vbrk):
    result = validate_file(spark, write_run(tmp_path, [docs(1)]), vbrk)
    types = dict(result.valid_df.dtypes)
    assert types["NETWR"] == "string"
    assert types["FKDAT"] == "string"
    assert types["_change_ts"] == "timestamp"


def test_failed_run(spark, tmp_path, vbrk):
    folder = write_run(tmp_path, [docs(2)], status="FAILED")
    result = validate_file(spark, folder, vbrk)
    assert result.reject_reason == "failed_run"


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"log_parts": 3}, "2 part file(s) found, task log says 3"),
        ({"log_rows": 10}, "4 row(s) found, task log says 10"),
        ({"status": "RUNNING"}, "not COMPLETED"),
        ({"write_log": False}, "task log not found"),
    ],
)
def test_incomplete_run(spark, tmp_path, vbrk, kwargs, detail):
    folder = write_run(tmp_path, [docs(2), docs(2, start=3)], **kwargs)
    result = validate_file(spark, folder, vbrk)
    assert result.reject_reason == "incomplete_run"
    assert detail in result.reject_detail


def test_missing_part_file_is_incomplete(spark, tmp_path, vbrk):
    folder = write_run(tmp_path, [docs(2), docs(2, start=3), docs(1, start=5)])
    (folder / "part-00001.parquet").unlink()
    result = validate_file(spark, folder, vbrk)
    assert result.reject_reason == "incomplete_run"


def test_task_log_without_this_object(spark, tmp_path, vbrk):
    folder = write_run(tmp_path, [docs(1)])
    log_path = tmp_path / "sap/PS4/_tasklog/PS4-20260929-0001.json"
    log = json.loads(log_path.read_text())
    log["objects"] = [{"object": "VBRP", "part_files": 1, "rows": 1}]
    log_path.write_text(json.dumps(log))
    assert "no entry for VBRK" in validate_file(spark, folder, vbrk).reject_detail


def test_unreadable_part_file_is_corrupt(spark, tmp_path, vbrk):
    folder = write_run(tmp_path, [docs(2)])
    part = folder / "part-00000.parquet"
    part.write_bytes(part.read_bytes()[:40])
    assert validate_file(spark, folder, vbrk).reject_reason == "corrupt_file"


def test_missing_required_column(spark, tmp_path, vbrk):
    rows = [{k: v for k, v in r.items() if k != "FKART"} for r in docs(2)]
    result = validate_file(spark, write_run(tmp_path, [rows]), vbrk)
    assert (result.reject_reason, result.reject_detail) == ("missing_column", "FKART")


def test_new_column_is_schema_drift_warning(spark, tmp_path, contracts):
    rows = [
        {
            **vbrk_row(),
            "POSNR": "000010",
            "MATNR": "0" * 12 + "400123",
            "FKIMG": "2.000",
            "VRKME": "EA",
            "WERKS": "US01",
            "ZZ_CONTRACT": "C-1",
        }
    ]
    keep = {c.name for c in contracts["sap_vbrp"].columns} | {"ZZ_CONTRACT"}
    rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
    folder = write_run(tmp_path, [rows], obj="VBRP")
    result = validate_file(spark, folder, contracts["sap_vbrp"])
    assert result.status == "accepted_with_warnings"
    assert result.warnings == [{"code": "schema_drift", "columns": ["ZZ_CONTRACT"]}]
    assert "ZZ_CONTRACT" in result.valid_df.columns


def test_empty_billing_run_is_rejected(spark, tmp_path, vbrk):
    folder = write_run(tmp_path, [[]])
    assert validate_file(spark, folder, vbrk).reject_reason == "empty_file"


def test_empty_master_data_run_is_allowed(spark, tmp_path, contracts):
    folder = write_run(tmp_path, [], obj="KNA1")
    result = validate_file(spark, folder, contracts["sap_kna1"])
    assert result.status == "accepted"
    assert result.row_count_in == 0


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"NETWR": "-5.00"}, "out_of_range"),
        ({"NETWR": "1500.005"}, "bad_type"),
        ({"FKDAT": "20261345"}, "bad_type"),
        ({"FKDAT": "00000000"}, "missing_value"),
        ({"FKART": "ZZ"}, "bad_value"),
        ({"VBELN": "90000099"}, "bad_format"),
        ({"VBELN": None}, "missing_key"),
        ({"_source_system": "XX1"}, "bad_value"),
    ],
)
def test_row_level_reasons(spark, tmp_path, vbrk, override, reason):
    bad = vbrk_row(**{"VBELN": "0090000099", "_seq": 99, **override})
    result = validate_file(spark, write_run(tmp_path, [[*docs(2), bad]]), vbrk)
    assert result.reason_counts == {reason: 1}


def test_delete_row_may_leave_non_key_fields_empty(spark, tmp_path, contracts):
    knvv = contracts["sap_knvv"]
    row = {
        "KUNNR": "0000100001",
        "VKORG": "1000",
        "VTWEG": "10",
        "SPART": "00",
        "BZIRK": "",
        "KDGRP": "",
        "VKBUR": "",
        "_op": "D",
        "_change_ts": datetime(2026, 9, 29, 2, 0, tzinfo=UTC),
        "_seq": 5,
        "_extract_id": "PS4-20260929-0001",
        "_source_system": "PS4",
    }
    insert_without_district = {**row, "_op": "I", "KUNNR": "0000100002"}
    folder = write_run(tmp_path, [[row, insert_without_district]], obj="KNVV")
    result = validate_file(spark, folder, knvv)
    assert result.reason_counts == {"missing_value": 1}
    assert result.valid_df.first()._op == "D"


def test_key_collision_keeps_highest_seq_as_a_number(spark, tmp_path, vbrk):
    ts = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    rows = [
        vbrk_row(_seq=10, RFBSK="C", _op="U", _change_ts=ts),
        vbrk_row(_seq=9, RFBSK="A", _op="I", _change_ts=ts),  # out of order in the file
    ]
    result = validate_file(spark, write_run(tmp_path, [rows]), vbrk)
    assert result.reason_counts == {"key_collision": 1}
    kept = result.valid_df.collect()
    assert [(r._seq, r.RFBSK) for r in kept] == [(10, "C")]


def test_change_ts_orders_before_seq(spark, tmp_path, vbrk):
    rows = [
        vbrk_row(_seq=1, RFBSK="C", _change_ts=datetime(2026, 9, 29, 3, 0, tzinfo=UTC)),
        vbrk_row(_seq=2, RFBSK="A", _change_ts=datetime(2026, 9, 29, 2, 0, tzinfo=UTC)),
    ]
    result = validate_file(spark, write_run(tmp_path, [rows]), vbrk)
    assert result.valid_df.first().RFBSK == "C"


def test_exact_duplicate_row(spark, tmp_path, vbrk):
    rows = docs(2)
    result = validate_file(spark, write_run(tmp_path, [[*rows, rows[1]]]), vbrk)
    assert result.reason_counts == {"duplicate_row": 1}
    assert result.row_count_valid == 2
