"""Fixtures for the contract tests."""

from pathlib import Path

import pytest

from halvern.contracts import load_contracts

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def contracts():
    return {c.name: c for c in load_contracts(REPO / "contracts")}
