"""Shared MediaWiki test fixtures."""

from __future__ import annotations

import bz2
import gzip
import shutil
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "mediawiki"
TINY_XML = FIXTURE_DIR / "tiny.xml"


def ensure_compressed_fixtures(tmp_path: Path | None = None) -> dict[str, Path]:
    """Return plain, gzip, and bzip2 paths for the tiny fixture."""
    base = tmp_path or FIXTURE_DIR
    plain = TINY_XML
    gz_path = base / "tiny.xml.gz"
    bz2_path = base / "tiny.xml.bz2"
    if tmp_path is not None:
        shutil.copy(plain, base / "tiny.xml")
        plain = base / "tiny.xml"
    with plain.open("rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    with plain.open("rb") as src, bz2.open(bz2_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return {"plain": plain, "gzip": gz_path, "bzip2": bz2_path}
