# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # Run checks: lint and unit tests on this branch
# MAGIC
# MAGIC The same checks the CI pipeline runs on every push. Run this notebook on your branch before
# MAGIC you merge it into `develop`, and again after syncing `develop` into your branch.
# MAGIC
# MAGIC | Check | Tool | Pass condition |
# MAGIC | --- | --- | --- |
# MAGIC | Code errors and style | `ruff check` | no findings |
# MAGIC | Layout | `ruff format --check` | no file would be reformatted |
# MAGIC | Unit tests | `pytest -m "not integration"` | all pass, coverage of `src/halvern` and the generator at least 70% |
# MAGIC
# MAGIC Notes:
# MAGIC - Use a single-node cluster. Tests that write small Parquet files use the driver's local disk.
# MAGIC - Tool versions match `requirements-dev.txt` and `.github/workflows/ci.yml`.
# MAGIC - Nothing is written into the Git folder: no bytecode, no caches, coverage data in `/tmp`.
# MAGIC   Otherwise those files would show up as changes in the Git dialog.

# COMMAND ----------

# MAGIC %pip install --quiet ruff==0.17.0 "pytest>=8.0" "pytest-cov>=5.0" "chispa>=0.10"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os
import subprocess
import sys

sys.dont_write_bytecode = True

root = os.getcwd()
while not (os.path.isfile(f"{root}/pyproject.toml") and os.path.isdir(f"{root}/src")):
    if os.path.dirname(root) == root:
        raise RuntimeError("Run this notebook from inside the halvern-data-platform Git folder")
    root = os.path.dirname(root)
os.chdir(root)
os.makedirs("/tmp/halvern_checks", exist_ok=True)
os.environ["COVERAGE_FILE"] = "/tmp/halvern_checks/.coverage"
print("Repository root:", root)


def run(command: list[str]) -> int:
    print("$", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout + result.stderr)
    return result.returncode

# COMMAND ----------

# MAGIC %md ## 1. Lint

# COMMAND ----------

lint_failures = sum(
    [
        run([sys.executable, "-m", "ruff", "check", "--no-cache", "."]) != 0,
        run([sys.executable, "-m", "ruff", "format", "--check", "--no-cache", "."]) != 0,
    ]
)
print("LINT:", "PASS" if lint_failures == 0 else "FAIL")

# COMMAND ----------

# MAGIC %md ## 2. Unit tests

# COMMAND ----------

import pytest

exit_code = pytest.main(
    [
        "-m",
        "not integration",
        "-p",
        "no:cacheprovider",
        "--cov=src/halvern",
        "--cov=generator/halvern_gen",
        "--cov-report=term-missing",
        "--cov-fail-under=70",
        "-q",
    ]
)
print("UNIT TESTS:", "PASS" if exit_code == 0 else "FAIL")

# COMMAND ----------

# MAGIC %md ## 3. Result

# COMMAND ----------

if lint_failures or exit_code != 0:
    raise RuntimeError("Checks failed: fix the findings above before merging into develop.")
print("ALL CHECKS PASS: this branch may be merged into develop.")