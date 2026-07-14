"""Streaming MediaWiki XML dump page iterator."""

from __future__ import annotations

import bz2
import gzip
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import BinaryIO
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MAX_REVISION_TEXT_BYTES = 32 * 1024 * 1024

CompressionKind = Literal["plain", "gzip", "bzip2"]


class MediaWikiXmlError(Exception):
    """Raised when dump input cannot be parsed or is unsupported."""


@dataclass(frozen=True)
class MediaWikiPage:
    title: str
    namespace: int
    page_id: int
    redirect_target: str | None
    revision_id: int | None
    revision_timestamp: str | None
    revision_sha1: str | None
    revision_text: str


def _local_tag(element: ET.Element) -> str:
    tag = element.tag
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(element: ET.Element, tag_name: str) -> str | None:
    for child in element:
        if _local_tag(child) == tag_name:
            return child.text
    return None


def _child_int(element: ET.Element, tag_name: str) -> int | None:
    value = _child_text(element, tag_name)
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def detect_compression(path: Path, header: bytes) -> CompressionKind:
    name = path.name.lower()
    if header.startswith(b"\x1f\x8b"):
        return "gzip"
    if header.startswith(b"BZh"):
        return "bzip2"
    if name.endswith(".xml.gz"):
        return "gzip"
    if name.endswith(".xml.bz2"):
        return "bzip2"
    if name.endswith(".7z"):
        msg = f"Unsupported compression format (.7z): {path}"
        raise MediaWikiXmlError(msg)
    if name.endswith(".sql") or name.endswith(".sql.gz") or name.endswith(".sql.bz2"):
        msg = f"SQL dumps are not supported: {path}"
        raise MediaWikiXmlError(msg)
    if "multistream" in name or name.endswith("-index.txt") or "-index" in name:
        msg = f"Multistream index files are not supported: {path}"
        raise MediaWikiXmlError(msg)
    if header.lstrip().startswith(b"<?xml") or header.lstrip().startswith(b"<"):
        return "plain"
    msg = f"Unknown or unsupported dump format: {path}"
    raise MediaWikiXmlError(msg)


def validate_dump_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        msg = f"Dump file does not exist: {path}"
        raise MediaWikiXmlError(msg)
    if resolved.is_dir():
        msg = f"Expected a dump file, got directory: {path}"
        raise MediaWikiXmlError(msg)
    if not resolved.is_file():
        msg = f"Unreadable dump path: {path}"
        raise MediaWikiXmlError(msg)
    return resolved


def open_dump_stream(path: Path) -> tuple[BinaryIO, CompressionKind]:
    resolved = validate_dump_path(path)
    with resolved.open("rb") as probe:
        header = probe.read(4)
    compression = detect_compression(resolved, header)
    raw = resolved.open("rb")
    if compression == "gzip":
        return gzip.open(raw, mode="rb"), compression  # type: ignore[return-value]
    if compression == "bzip2":
        return bz2.open(raw, mode="rb"), compression  # type: ignore[return-value]
    return raw, compression


def _parse_page_element(page_elem: ET.Element) -> MediaWikiPage:
    title = _child_text(page_elem, "title")
    if title is None or not title.strip():
        msg = "Page missing title"
        raise MediaWikiXmlError(msg)

    page_id = _child_int(page_elem, "id")
    if page_id is None:
        msg = f"Page missing id: {title!r}"
        raise MediaWikiXmlError(msg)

    namespace = _child_int(page_elem, "ns")
    if namespace is None:
        namespace = 0

    redirect_target: str | None = None
    for child in page_elem:
        if _local_tag(child) == "redirect":
            redirect_target = child.get("title")
            break

    revision_elem: ET.Element | None = None
    for child in page_elem:
        if _local_tag(child) == "revision":
            revision_elem = child

    revision_id: int | None = None
    revision_timestamp: str | None = None
    revision_sha1: str | None = None
    revision_text = ""

    if revision_elem is not None:
        revision_id = _child_int(revision_elem, "id")
        revision_timestamp = _child_text(revision_elem, "timestamp")
        revision_sha1 = _child_text(revision_elem, "sha1")
        text_elem: ET.Element | None = None
        for child in revision_elem:
            if _local_tag(child) == "text":
                text_elem = child
        if text_elem is not None:
            revision_text = text_elem.text or ""
            if len(revision_text.encode("utf-8")) > MAX_REVISION_TEXT_BYTES:
                msg = (
                    f"Revision text exceeds {MAX_REVISION_TEXT_BYTES} bytes "
                    f"for page {page_id!r}"
                )
                raise MediaWikiXmlError(msg)

    if revision_elem is None:
        msg = f"Page missing revision: {title!r}"
        raise MediaWikiXmlError(msg)

    return MediaWikiPage(
        title=title,
        namespace=namespace,
        page_id=page_id,
        redirect_target=redirect_target,
        revision_id=revision_id,
        revision_timestamp=revision_timestamp,
        revision_sha1=revision_sha1,
        revision_text=revision_text,
    )


def iter_mediawiki_pages(stream: BinaryIO) -> Iterator[MediaWikiPage]:
    """Stream pages from a MediaWiki XML dump without loading the full tree."""
    context = ET.iterparse(stream, events=("end",))
    saw_mediawiki = False
    for _event, elem in context:
        tag = _local_tag(elem)
        if tag == "mediawiki":
            saw_mediawiki = True
        if tag != "page":
            continue
        try:
            page = _parse_page_element(elem)
        finally:
            elem.clear()
        yield page

    if not saw_mediawiki:
        msg = "Input is not a MediaWiki XML dump (missing <mediawiki> root element)"
        raise MediaWikiXmlError(msg)


def iter_mediawiki_pages_from_path(path: Path) -> Iterator[MediaWikiPage]:
    """Open a local dump and yield pages."""
    stream, _compression = open_dump_stream(path)
    try:
        yield from iter_mediawiki_pages(stream)
    finally:
        stream.close()
