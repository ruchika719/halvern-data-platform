"""validate_folder: find files, match them to contracts, write the JSON report."""

import json

import pytest
from builders import northline_row, pacifica_row, vbrk_row, write_csv, write_pacifica, write_run

from halvern.contracts import validate_folder as vf
from halvern.contracts.model import load_contracts

pytestmark = pytest.mark.contract

CONTRACTS = vf.Path(__file__).resolve().parents[2] / "contracts"


@pytest.fixture
def landing(tmp_path):
    root = tmp_path / "landing"
    nl = root / "wholesaler/northline/867/week_end=2026-09-27"
    write_csv(nl / "NL_867_20260927.csv", [northline_row()], qty_column="qty")
    write_csv(nl / "NL_867_20260927_v2.csv", [northline_row(qty="N/A")], qty_column="qty")
    write_pacifica(
        root / "wholesaler/pacifica/867/week_end=2026-09-27/PHS867_20260927.dat", [pacifica_row()]
    )
    write_run(root, [[vbrk_row()]], run_id="PS4-20260929-0001")
    # A failed run: VBRK files were written, VBRP never arrived.
    write_run(
        root,
        [[vbrk_row()]],
        run_id="PS4-20260930-0002",
        status="FAILED",
        other_objects=[{"object": "VBRP", "part_files": 1, "rows": 1}],
    )
    write_run(root, [[vbrk_row(_source_system="JE1")]], system="JE1", run_id="JE1-20260929-0001")
    (root / "wholesaler/unknown").mkdir(parents=True)
    (root / "wholesaler/unknown/stray.txt").write_text("?")
    return root


def test_match_contract_by_path():
    contracts = load_contracts(CONTRACTS)
    match = lambda rel: getattr(vf.match_contract(rel, contracts), "name", None)  # noqa: E731
    assert match("sap/PS4/VBRK/delta/run1/part-00000.parquet") == "sap_vbrk"
    assert match("sap/JE1/VBRP/initial/run1/part-00003.parquet") == "sap_vbrp"
    assert match("sap/JE1/KNA1/initial/run1/part-00000.parquet") is None  # JE1 is billing only
    assert match("sap/PS4/VBRK/run1/part-00000.parquet") is None
    assert match("wholesaler/northline/867/week_end=2026-09-27/NL_867_20260927.csv") == (
        "wholesaler_northline_867"
    )
    assert match("wholesaler/crestway/867/week_end=x/CW_SALES_092726.csv") == (
        "wholesaler_crestway_867"
    )
    assert match("wholesaler/pacifica/867/week_end=x/PHS867_20260927.dat") == (
        "wholesaler_pacifica_867"
    )
    assert match("reference/wholesaler_item_xref/load_date=x/xref_20260929.csv") == (
        "reference_wholesaler_item_xref"
    )
    assert match("wholesaler/northline/867/notes.csv") is None


def test_report(spark, tmp_path, landing):
    report_path = tmp_path / "reports" / "validation.json"
    args = [str(landing), "--contracts", str(CONTRACTS), "--report", str(report_path)]
    assert vf.main(args, spark=spark) == 0
    report = json.loads(report_path.read_text())

    by_path = {f["file_path"].removeprefix(str(landing) + "/"): f for f in report["files"]}
    assert set(by_path) == {
        "wholesaler/northline/867/week_end=2026-09-27/NL_867_20260927.csv",
        "wholesaler/northline/867/week_end=2026-09-27/NL_867_20260927_v2.csv",
        "wholesaler/pacifica/867/week_end=2026-09-27/PHS867_20260927.dat",
        "sap/PS4/VBRK/delta/PS4-20260929-0001",
        "sap/PS4/VBRK/delta/PS4-20260930-0002",
        "sap/PS4/VBRP/delta/PS4-20260930-0002",
        "sap/JE1/VBRK/delta/JE1-20260929-0001",
    }
    assert by_path["sap/PS4/VBRK/delta/PS4-20260929-0001"]["status"] == "accepted"
    assert by_path["sap/PS4/VBRK/delta/PS4-20260930-0002"]["reject_reason"] == "failed_run"
    missing = by_path["sap/PS4/VBRP/delta/PS4-20260930-0002"]
    assert (missing["contract"], missing["reject_reason"]) == ("sap_vbrp", "failed_run")
    v2 = by_path["wholesaler/northline/867/week_end=2026-09-27/NL_867_20260927_v2.csv"]
    assert v2["reason_counts"] == {"bad_type": 1}

    summary = report["summary"]
    assert summary["files"] == 7
    assert summary["by_status"] == {"accepted": 5, "rejected": 2}
    assert summary["reason_counts"] == {"bad_type": 1, "failed_run": 2}
    assert summary["reason_counts_by_contract"]["sap_vbrp"] == {"failed_run": 1}
    assert report["unmatched_files"] == ["wholesaler/unknown/stray.txt"]
    assert report["generated_utc"].endswith("Z")


def test_completed_run_with_a_missing_object_folder(spark, tmp_path):
    root = tmp_path / "landing"
    write_run(root, [[vbrk_row()]], other_objects=[{"object": "VBRP", "part_files": 1, "rows": 3}])
    report = vf.validate_landing(spark, root, load_contracts(CONTRACTS))
    reasons = {f["contract"]: f["reject_reason"] for f in report["files"]}
    assert reasons == {"sap_vbrk": None, "sap_vbrp": "incomplete_run"}
