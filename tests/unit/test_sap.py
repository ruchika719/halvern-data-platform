"""Unit tests for halvern.common.sap."""

import datetime as dt
from decimal import Decimal

import pytest
from pyspark.sql import functions as F

from halvern.common import (
    billing_sign,
    currency_shift,
    invert_gdatu,
    sap_date,
    sap_rate,
    strip_sap_zeros,
)

pytestmark = pytest.mark.unit


def apply(spark, func, values, schema="v string"):
    """Run a one-argument column function over values and return the results in order."""
    rows = [(i, v) for i, v in enumerate(values)]
    df = spark.createDataFrame(rows, f"i int, {schema}")
    return [r.out for r in df.select("i", func(F.col("v")).alias("out")).orderBy("i").collect()]


def test_strip_sap_zeros(spark):
    values = ["000000000000400123", "0000000000", "ABC0012", "", None, "  ", "42"]
    assert apply(spark, strip_sap_zeros, values) == [
        "400123",
        "0",
        "ABC0012",
        None,
        None,
        None,
        "42",
    ]


def test_strip_sap_zeros_accepts_column_name(spark):
    df = spark.createDataFrame([("0000000123",)], "KUNNR string")
    assert df.select(strip_sap_zeros("KUNNR").alias("k")).first().k == "123"


def test_sap_date(spark):
    values = ["20260929", "00000000", "20261345", "20280229", "20270229", "", None, "2026-09-29"]
    assert apply(spark, sap_date, values) == [
        dt.date(2026, 9, 29),
        None,
        None,
        dt.date(2028, 2, 29),
        None,
        None,
        None,
        None,
    ]


def test_invert_gdatu(spark):
    assert apply(spark, invert_gdatu, ["79739070", "", None, "ABCDEFGH"]) == [
        dt.date(2026, 9, 29),
        None,
        None,
        None,
    ]


def test_invert_gdatu_round_trip(spark):
    assert 99999999 - 20260929 == 79739070
    assert apply(spark, invert_gdatu, ["79739070"]) == [dt.date(2026, 9, 29)]


def test_currency_shift(spark):
    df = spark.createDataFrame(
        [(1, "10.00", "JPY"), (2, "10.00", "EUR"), (3, "10.00", "KWD"), (4, "5.50", None)],
        "i int, amount string, waers string",
    )
    out = df.select(
        "i", currency_shift("amount", "waers", {"JPY": 0, "KWD": 3}).alias("real")
    ).orderBy("i")
    assert [r.real for r in out.collect()] == [
        Decimal("1000"),
        Decimal("10"),
        Decimal("1"),
        Decimal("5.5"),
    ]


def test_currency_shift_null_amount(spark):
    df = spark.createDataFrame([(None, "JPY")], "amount string, waers string")
    assert df.select(currency_shift("amount", "waers", {"JPY": 0}).alias("r")).first().r is None


def test_sap_rate(spark):
    df = spark.createDataFrame(
        [
            (1, "1.08000", "1", "1"),  # EUR -> USD, direct
            (2, "-0.80000", "1", "1"),  # GBP -> USD, indirect
            (3, "0.68000", "100", "1"),  # JPY -> USD per 100 JPY
            (4, "0", "1", "1"),
            (5, "1.10000", "0", "1"),
            (6, None, "1", "1"),
        ],
        "i int, ukurs string, ffact string, tfact string",
    )
    out = df.select("i", sap_rate("ukurs", "ffact", "tfact").alias("rate")).orderBy("i")
    assert [r.rate for r in out.collect()] == [
        Decimal("1.08"),
        Decimal("1.25"),
        Decimal("0.0068"),
        None,
        None,
        None,
    ]


def test_billing_sign(spark):
    values = ["F2", "L2", "IV", "G2", "RE", "S1", "ZZ", None]
    assert apply(spark, billing_sign, values) == [1, 1, 1, -1, -1, -1, None, None]


def test_billing_sign_custom_map(spark):
    assert apply(spark, lambda c: billing_sign(c, {"ZF": -1}), ["ZF", "F2"]) == [-1, None]
