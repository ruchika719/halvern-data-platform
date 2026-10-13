"""Unit tests for halvern.common.frames."""

import pytest
from chispa import assert_df_equality

from halvern.common import cast_seq, dedupe_latest, row_hash

pytestmark = pytest.mark.unit


def test_dedupe_latest_keeps_highest_order(spark):
    df = spark.createDataFrame(
        [
            ("A", "2026-09-29T01:00:00Z", 1, "old"),
            ("A", "2026-09-29T02:00:00Z", 1, "new"),
            ("B", "2026-09-29T01:00:00Z", 9, "first"),
            ("B", "2026-09-29T01:00:00Z", 10, "tie broken by seq"),
            ("C", "2026-09-29T01:00:00Z", 1, "only"),
        ],
        "k string, _change_ts string, _seq int, v string",
    )
    result = dedupe_latest(df, ["k"], ["_change_ts", "_seq"])
    expected = spark.createDataFrame(
        [
            ("A", "2026-09-29T02:00:00Z", 1, "new"),
            ("B", "2026-09-29T01:00:00Z", 10, "tie broken by seq"),
            ("C", "2026-09-29T01:00:00Z", 1, "only"),
        ],
        df.schema,
    )
    assert_df_equality(result, expected, ignore_row_order=True)


def test_seq_as_text_keeps_the_wrong_row(spark):
    # The trap cast_seq exists for: as text, "9" sorts above "10".
    df = spark.createDataFrame(
        [("A", "9", "older"), ("A", "10", "newer")], "k string, _seq string, v string"
    )
    assert dedupe_latest(df, ["k"], ["_seq"]).first().v == "older"


def test_cast_seq_then_dedupe_keeps_seq_10_over_9(spark):
    df = spark.createDataFrame(
        [("A", "9", "older"), ("A", "10", "newer")], "k string, _seq string, v string"
    )
    typed = cast_seq(df)
    assert dict(typed.dtypes)["_seq"] == "bigint"
    result = dedupe_latest(typed, ["k"], ["_seq"]).collect()
    assert [(r.v, r._seq) for r in result] == [("newer", 10)]


def test_cast_seq_bad_values_become_null(spark):
    df = spark.createDataFrame([("x1", "12"), ("x2", "N/A"), ("x3", None)], "id string, s string")
    out = cast_seq(df, seq_col="s").orderBy("id").collect()
    assert [r.s for r in out] == [12, None, None]


def test_dedupe_latest_excludes_null_keys_and_uses_composite_keys(spark):
    df = spark.createDataFrame(
        [
            ("A", "1", 1, "a1"),
            ("A", "1", 2, "a1-latest"),
            ("A", "2", 1, "a2"),
            (None, "1", 5, "null key"),
            ("B", None, 5, "null key part"),
        ],
        "k1 string, k2 string, _seq int, v string",
    )
    result = dedupe_latest(df, ["k1", "k2"], ["_seq"])
    assert sorted(r.v for r in result.collect()) == ["a1-latest", "a2"]
    assert result.columns == df.columns


def test_dedupe_latest_requires_keys_and_order(spark):
    df = spark.createDataFrame([("A", 1)], "k string, _seq int")
    with pytest.raises(ValueError):
        dedupe_latest(df, [], ["_seq"])
    with pytest.raises(ValueError):
        dedupe_latest(df, ["k"], [])


def hashes(spark, rows, cols, schema="a string, b string"):
    df = spark.createDataFrame(rows, schema)
    return [r._row_hash for r in row_hash(df, cols).collect()]


def test_row_hash_null_and_empty_differ(spark):
    h_null, h_empty = hashes(spark, [("x", None), ("x", "")], ["a", "b"])
    assert h_null != h_empty


def test_row_hash_column_order_matters(spark):
    rows = [("x", "y")]
    assert hashes(spark, rows, ["a", "b"]) != hashes(spark, rows, ["b", "a"])


def test_row_hash_is_stable_sha256(spark):
    h1, h2 = hashes(spark, [("x", "y"), ("x", "y")], ["a", "b"])
    assert h1 == h2
    assert len(h1) == 64


def test_row_hash_separator_prevents_shifted_values(spark):
    h1, h2 = hashes(spark, [("ab", "c"), ("a", "bc")], ["a", "b"])
    assert h1 != h2


def test_row_hash_custom_output_and_empty_cols(spark):
    df = spark.createDataFrame([("x", "y")], "a string, b string")
    assert "h" in row_hash(df, ["a"], output_col="h").columns
    with pytest.raises(ValueError):
        row_hash(df, [])
