"""Trivial checks that the packages import and local Spark starts (HDP-1)."""

import pytest
from chispa import assert_df_equality

import halvern
import halvern_gen
from halvern_gen import cli

pytestmark = pytest.mark.unit


def test_packages_have_versions():
    assert halvern.__version__ == "0.1.0"
    assert halvern_gen.__version__ == "0.1.0"


def test_cli_main_runs(capsys):
    assert cli.main([]) == 0
    assert "halvern-gen" in capsys.readouterr().out


def test_spark_session_is_utc(spark):
    assert spark.conf.get("spark.sql.session.timeZone") == "UTC"
    df = spark.createDataFrame([(1, "a")], ["id", "value"])
    assert_df_equality(df, spark.createDataFrame([(1, "a")], ["id", "value"]))
