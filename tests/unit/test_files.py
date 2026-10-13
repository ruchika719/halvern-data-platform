"""Unit tests for halvern.common.files."""

import hashlib

import pytest

from halvern.common import file_fingerprint

pytestmark = pytest.mark.unit


def test_same_bytes_same_hash(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_bytes(b"VBELN,POSNR\n0090000001,000010\n")
    b.write_bytes(a.read_bytes())
    assert file_fingerprint(a) == file_fingerprint(b)
    assert file_fingerprint(a) == hashlib.sha256(a.read_bytes()).hexdigest()


def test_renamed_file_same_hash(tmp_path):
    a = tmp_path / "KNA1_20260929T010512Z_PS4_000123.csv"
    a.write_bytes(b"data")
    before = file_fingerprint(a)
    renamed = a.rename(tmp_path / "copy_of_extract.csv")
    assert file_fingerprint(renamed) == before


def test_different_bytes_different_hash(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    assert file_fingerprint(a) != file_fingerprint(b)


def test_large_file_read_in_chunks(tmp_path):
    big = tmp_path / "big.bin"
    content = b"0123456789" * 300_000  # 3 MB, more than one chunk
    big.write_bytes(content)
    assert file_fingerprint(str(big)) == hashlib.sha256(content).hexdigest()
