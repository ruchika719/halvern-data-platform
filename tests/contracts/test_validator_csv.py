"""validate_file on CSV partner files: one hand-made file per reason code."""

import json

import pytest
from builders import northline_row, write_csv, write_ctl

from halvern.contracts import validate_file

pytestmark = pytest.mark.contract

NL = "wholesaler_northline_867"


@pytest.fixture
def northline(contracts):
    return contracts[NL]


def nl_file(tmp_path, rows, **kwargs):
    return write_csv(tmp_path / "NL_867_20260927.csv", rows, qty_column="qty", **kwargs)


def rows(n=3):
    return [northline_row(invoice_no=f"INV{i:04d}", qty=str(i + 1)) for i in range(n)]


def test_clean_file_is_accepted(spark, tmp_path, northline):
    result = validate_file(spark, nl_file(tmp_path, rows()), northline)
    assert result.status == "accepted"
    assert (result.row_count_in, result.row_count_valid, result.row_count_quarantined) == (3, 3, 0)
    assert result.reason_counts == {}
    assert result.valid_df.count() == 3
    assert {"_file_name", "_row_number"} <= set(result.valid_df.columns)


def quarantined(spark, tmp_path, contract, bad_row):
    result = validate_file(spark, nl_file(tmp_path, [*rows(2), bad_row]), contract)
    assert result.status == "accepted"
    assert result.row_count_quarantined == 1
    assert result.row_count_valid == 2
    return result


@pytest.mark.parametrize(
    ("override", "reason", "detail"),
    [
        ({"ndc11": ""}, "missing_key", "ndc11="),
        ({"cust_name": "  "}, "missing_value", "cust_name=  "),
        ({"qty": "N/A"}, "bad_type", "qty=N/A"),
        ({"qty": "1.5"}, "bad_type", "qty=1.5"),
        ({"invoice_date": "2026-13-45"}, "bad_type", "invoice_date=2026-13-45"),
        ({"cust_zip": "1234"}, "bad_format", "cust_zip=1234"),
        ({"uom": "EA"}, "bad_value", "uom=EA"),
    ],
)
def test_row_level_reasons(spark, tmp_path, northline, override, reason, detail):
    bad = northline_row(invoice_no="INV9999", **override)
    result = quarantined(spark, tmp_path, northline, bad)
    assert result.reason_counts == {reason: 1}
    q = result.quarantine_df.collect()[0]
    assert (q._reason_code, q._reason_detail) == (reason, detail)
    assert q._row_number == 3
    assert q._file_name.endswith("NL_867_20260927.csv")
    assert q.invoice_no == "INV9999"


def test_missing_key_wins_over_other_problems(spark, tmp_path, northline):
    bad = northline_row(invoice_no="INV9999", ndc11="", qty="N/A")
    result = quarantined(spark, tmp_path, northline, bad)
    assert result.reason_counts == {"missing_key": 1}


def test_duplicate_row_is_counted_not_quarantined(spark, tmp_path, northline):
    data = rows(2)
    result = validate_file(spark, nl_file(tmp_path, [*data, data[0]]), northline)
    assert result.reason_counts == {"duplicate_row": 1}
    assert (result.row_count_in, result.row_count_valid, result.row_count_quarantined) == (3, 2, 0)


def test_key_collision_keeps_the_later_row(spark, tmp_path, northline):
    # Northline has no order columns, so the later row in the file wins.
    data = [*rows(2), northline_row(invoice_no="INV0000", qty="7")]
    result = validate_file(spark, nl_file(tmp_path, data), northline)
    assert result.reason_counts == {"key_collision": 1}
    kept = [r for r in result.valid_df.collect() if r.invoice_no == "INV0000"]
    assert [r.qty for r in kept] == ["7"]


def test_counts_add_up(spark, tmp_path, northline):
    data = rows(4)
    data += [data[0], northline_row(invoice_no="INV0001", qty="9"), northline_row(qty="N/A")]
    result = validate_file(spark, nl_file(tmp_path, data), northline)
    counted = (
        result.row_count_valid
        + result.row_count_quarantined
        + result.reason_counts["duplicate_row"]
        + result.reason_counts["key_collision"]
    )
    assert counted == result.row_count_in == 7


def test_short_line_in_the_middle_is_quarantined(spark, tmp_path, northline):
    path = nl_file(tmp_path, rows(3))
    lines = path.read_text().splitlines()
    lines.insert(2, "2026-09-27,DC01,12345067890")
    path.write_text("\n".join(lines) + "\n")
    write_ctl(path, [*rows(3), {}], "qty")
    result = validate_file(spark, path, northline)
    assert result.reason_counts == {"bad_format": 1}
    assert "fields, expected 11" in result.quarantine_df.first()._reason_detail


def assert_rejected(result, reason, detail=""):
    assert result.status == "rejected"
    assert result.reject_reason == reason
    assert detail in result.reject_detail
    assert result.valid_df is None and result.quarantine_df is None
    assert result.reason_counts == {reason: 1}


def test_missing_column(spark, tmp_path, northline):
    data = [{k: v for k, v in r.items() if k != "cust_zip"} for r in rows()]
    assert_rejected(validate_file(spark, nl_file(tmp_path, data), northline), "missing_column")


def test_missing_optional_column_is_fine(spark, tmp_path, northline):
    data = [{k: v for k, v in r.items() if k != "contract_id"} for r in rows()]
    assert validate_file(spark, nl_file(tmp_path, data), northline).status == "accepted"


def test_unexpected_column_when_new_columns_not_allowed(spark, tmp_path, northline):
    data = [{**r, "rebate": "1"} for r in rows()]
    result = validate_file(spark, nl_file(tmp_path, data), northline)
    assert_rejected(result, "unexpected_column", "rebate")


def test_empty_file(spark, tmp_path, northline):
    path = tmp_path / "NL_867_20260927.csv"
    path.write_text(",".join(northline_row()) + "\n")
    write_ctl(path, [], "qty")
    assert_rejected(validate_file(spark, path, northline), "empty_file")


def test_corrupt_file_truncated_last_line(spark, tmp_path, northline):
    path = nl_file(tmp_path, rows(3))
    text = path.read_text()
    path.write_text(text[: text.rindex(",", 0, len(text) - 20)])
    write_ctl(path, rows(3), "qty")
    assert_rejected(validate_file(spark, path, northline), "corrupt_file", "last line")


@pytest.mark.parametrize(
    ("ctl_change", "detail"),
    [
        ({"row_count": 4}, "row_count"),
        ({"total_qty": 999}, "total_qty"),
        ({"file_sha256": "0" * 64}, "file_sha256"),
        ({"row_count": "many"}, "unreadable"),
    ],
)
def test_control_mismatch(spark, tmp_path, northline, ctl_change, detail):
    path = nl_file(tmp_path, rows(3), ctl=False)
    write_ctl(path, rows(3), "qty", **ctl_change)
    assert_rejected(validate_file(spark, path, northline), "control_mismatch", detail)


def test_control_file_missing(spark, tmp_path, northline):
    path = nl_file(tmp_path, rows(3), ctl=False)
    assert_rejected(validate_file(spark, path, northline), "control_mismatch", "missing")


def test_control_total_ignores_non_numeric_quantities(spark, tmp_path, northline):
    data = [*rows(2), northline_row(invoice_no="INV9", qty="N/A")]
    path = nl_file(tmp_path, data)
    assert json.loads(path.with_name(path.name + ".ctl").read_text())["total_qty"] == "3"
    assert validate_file(spark, path, northline).status == "accepted"


def crestway_rows():
    return [
        {
            "WEEK_END": "09/27/2026",
            "DC": "C1",
            "CW_ITEM": f"CW-{i}",
            "CUSTOMER": "CONFIDENTIAL",
            "ZIP": "30301",
            "QTY_CS": "3",
            "EXT_COST": "120.50",
        }
        for i in range(2)
    ]


def test_crestway_semicolon_and_us_dates(spark, tmp_path, contracts):
    path = write_csv(
        tmp_path / "CW_SALES_092726.csv", crestway_rows(), delimiter=";", qty_column="QTY_CS"
    )
    result = validate_file(spark, path, contracts["wholesaler_crestway_867"])
    assert result.status == "accepted"
    assert result.row_count_valid == 2


def test_crestway_bad_date_and_decimal(spark, tmp_path, contracts):
    data = crestway_rows()
    data[0]["WEEK_END"] = "2026-09-27"
    data[1]["EXT_COST"] = "1,200.00"
    path = write_csv(tmp_path / "CW_SALES_092726.csv", data, delimiter=";", qty_column="QTY_CS")
    result = validate_file(spark, path, contracts["wholesaler_crestway_867"])
    assert result.reason_counts == {"bad_type": 2}


def test_latin1_file_is_rejected_with_encoding_error(spark, tmp_path, contracts):
    data = crestway_rows()
    data[0]["CUSTOMER"] = "Apotheke Müller"
    path = tmp_path / "CW_SALES_092726.csv"
    header = list(data[0])
    text = ";".join(header) + "\n" + "\n".join(";".join(r[c] for c in header) for r in data)
    path.write_bytes((text + "\n").encode("latin-1"))
    write_ctl(path, data, "QTY_CS")
    result = validate_file(spark, path, contracts["wholesaler_crestway_867"])
    assert_rejected(result, "encoding_error", "utf-8")


def test_xref_has_no_control_file(spark, tmp_path, contracts):
    data = [
        {
            "wholesaler": "crestway",
            "wholesaler_item": "CW-1",
            "ndc11": "12345067890",
            "halvern_item": "000000000000400123",
            "valid_from": "2026-01-01",
            "valid_to": "9999-12-31",
        }
    ]
    path = write_csv(tmp_path / "xref_20260929.csv", data, ctl=False)
    result = validate_file(spark, path, contracts["reference_wholesaler_item_xref"])
    assert result.status == "accepted"
