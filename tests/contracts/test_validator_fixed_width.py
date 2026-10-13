"""validate_file on Pacifica fixed-width files."""

import pytest
from builders import pacifica_line, pacifica_row, write_ctl, write_pacifica

from halvern.contracts import validate_file

pytestmark = pytest.mark.contract


@pytest.fixture
def pacifica(contracts):
    return contracts["wholesaler_pacifica_867"]


def path_for(tmp_path):
    return tmp_path / "PHS867_20260927.dat"


def rows():
    return [
        pacifica_row(customer_no="00000001"),
        pacifica_row(customer_no="00000002", ndc10="1234-5678-90"),
        pacifica_row(customer_no="00000003", quantity="00000004", sign="-"),
    ]


def test_lines_are_55_characters():
    assert len(pacifica_line(pacifica_row())) == 55


def test_clean_file_is_accepted_and_trimmed(spark, tmp_path, pacifica):
    result = validate_file(spark, write_pacifica(path_for(tmp_path), rows()), pacifica)
    assert result.status == "accepted"
    assert result.row_count_valid == 3
    first = result.valid_df.orderBy("_row_number").first()
    assert (first.ndc10, first.sign, first.week_end) == ("12345-678-90", "", "20260927")


def test_negative_quantity_counts_in_control_total(spark, tmp_path, pacifica):
    path = write_pacifica(path_for(tmp_path), rows(), ctl=False)
    write_ctl(path, rows(), "quantity", total_qty=12 + 12 + 4)  # sign ignored: wrong
    result = validate_file(spark, path, pacifica)
    assert result.reject_reason == "control_mismatch"
    assert "total_qty 28" in result.reject_detail


def test_bad_record_length(spark, tmp_path, pacifica):
    lines = [pacifica_line(r) for r in rows()]
    lines[1] = lines[1][:50]
    path = write_pacifica(path_for(tmp_path), rows(), lines=lines)
    result = validate_file(spark, path, pacifica)
    assert result.reject_reason == "bad_record_length"
    assert "line 2 has 50 characters" in result.reject_detail


def test_empty_file(spark, tmp_path, pacifica):
    path = write_pacifica(path_for(tmp_path), [])
    assert validate_file(spark, path, pacifica).reject_reason == "empty_file"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"ndc10": "1234567890"}, "bad_format"),
        ({"ndc10": ""}, "missing_key"),
        ({"quantity": "0000N/A0"}, "bad_type"),
        ({"unit": "CS"}, "bad_value"),
        ({"week_end": "20261345"}, "bad_type"),
        ({"sign": "+"}, "bad_value"),
    ],
)
def test_row_level_reasons(spark, tmp_path, pacifica, override, reason):
    data = [*rows(), pacifica_row(customer_no="00000009", **override)]
    result = validate_file(spark, write_pacifica(path_for(tmp_path), data), pacifica)
    assert result.reason_counts == {reason: 1}
    assert result.quarantine_df.first()._row_number == 4
