"""Unit tests for halvern.common.frames."""

import pytest
from chispa import assert_df_equality

from halvern.common import dedupe_latest, row_hash

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
