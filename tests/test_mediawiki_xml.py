"""Tests for streaming MediaWiki XML parsing."""

from __future__ import annotations

import gzip
import bz2
from pathlib import Path

import pytest

from ark_pi.corpus.mediawiki_xml import (
    MediaWikiXmlError,
    detect_compression,
    iter_mediawiki_pages,
    iter_mediawiki_pages_from_path,
    open_dump_stream,
    validate_dump_path,
)
from tests.mediawiki_fixtures import TINY_XML, ensure_compressed_fixtures


@pytest.fixture
def mediawiki_paths(tmp_path: Path) -> dict[str, Path]:
    return ensure_compressed_fixtures(tmp_path)


def test_plain_xml_pages(mediawiki_paths: dict[str, Path]) -> None:
    pages = list(iter_mediawiki_pages_from_path(mediawiki_paths["plain"]))
    assert len(pages) == 5
    article = pages[0]
    assert article.title == "Fixture article"
    assert article.namespace == 0
    assert article.page_id == 1001
    assert article.revision_id == 5001


def test_gzip_input(mediawiki_paths: dict[str, Path]) -> None:
    pages = list(iter_mediawiki_pages_from_path(mediawiki_paths["gzip"]))
    assert pages[0].title == "Fixture article"


def test_bzip2_input(mediawiki_paths: dict[str, Path]) -> None:
    pages = list(iter_mediawiki_pages_from_path(mediawiki_paths["bzip2"]))
    assert pages[0].title == "Fixture article"


def test_magic_byte_detection(mediawiki_paths: dict[str, Path]) -> None:
    with mediawiki_paths["gzip"].open("rb") as handle:
        header = handle.read(4)
    assert detect_compression(mediawiki_paths["gzip"], header) == "gzip"
    with mediawiki_paths["bzip2"].open("rb") as handle:
        header = handle.read(4)
    assert detect_compression(mediawiki_paths["bzip2"], header) == "bzip2"


def test_redirect_page(mediawiki_paths: dict[str, Path]) -> None:
    pages = list(iter_mediawiki_pages_from_path(mediawiki_paths["plain"]))
    redirect = next(page for page in pages if page.page_id == 1004)
    assert redirect.redirect_target == "Fixture article"


def test_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(MediaWikiXmlError, match="directory"):
        validate_dump_path(tmp_path)


def test_rejects_multistream_index(tmp_path: Path) -> None:
    path = tmp_path / "simplewiki-multistream-index.txt"
    path.write_bytes(b"index")
    with pytest.raises(MediaWikiXmlError, match="Multistream"):
        open_dump_stream(path)


def test_rejects_non_mediawiki_xml(tmp_path: Path) -> None:
    path = tmp_path / "notwiki.xml"
    path.write_text("<root><item/></root>", encoding="utf-8")
    with pytest.raises(MediaWikiXmlError, match="not a MediaWiki"):
        list(iter_mediawiki_pages_from_path(path))


def test_malformed_page_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.xml"
    path.write_text(
        """<?xml version="1.0"?>
<mediawiki>
  <page>
    <title>Broken</title>
    <ns>0</ns>
    <id>999</id>
  </page>
</mediawiki>
""",
        encoding="utf-8",
    )
    with pytest.raises(MediaWikiXmlError, match="missing revision"):
        list(iter_mediawiki_pages_from_path(path))


def test_streaming_clears_elements(mediawiki_paths: dict[str, Path]) -> None:
    stream, _ = open_dump_stream(mediawiki_paths["plain"])
    try:
        iterator = iter_mediawiki_pages(stream)
        first = next(iterator)
        assert first.page_id == 1001
        second = next(iterator)
        assert second.page_id == 1002
    finally:
        stream.close()
