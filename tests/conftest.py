"""Shared pytest fixtures."""

import os

import pytest
from pyspark.sql import SparkSession

ON_DATABRICKS = "DATABRICKS_RUNTIME_VERSION" in os.environ


@pytest.fixture(scope="session")
def spark():
    """One SparkSession for the whole test run.

    Locally and in CI: a small local session, stopped at the end.
    On a Databricks cluster (the tools/run_checks notebook): the notebook's own session. It is
    never stopped, because stopping it would break every notebook attached to the cluster.
    """
    if ON_DATABRICKS:
        session = SparkSession.builder.getOrCreate()
        session.conf.set("spark.sql.session.timeZone", "UTC")
        session.conf.set("spark.sql.shuffle.partitions", "2")
        yield session
        return
    session = (
        SparkSession.builder.master("local[2]")
        .appName("halvern-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
