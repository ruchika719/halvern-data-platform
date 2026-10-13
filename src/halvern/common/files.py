"""Plain-Python file helpers."""

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def file_fingerprint(path: str | Path) -> str:
    """SHA-256 (hex) of a file's bytes, read in chunks. The file name does not matter."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
