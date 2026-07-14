"""Deterministic conservative wikitext normalization."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Protocol

NORMALIZER_VERSION = "ark-pi-wikipedia-v1"
MAX_TEMPLATE_DEPTH = 32
MAX_SCAN_CHARS = 512_000


@dataclass(frozen=True)
class NormalizedText:
    text: str
    visible_chars: int
    warnings: tuple[str, ...]


class WikitextNormalizer(Protocol):
    version: str

    def normalize(self, wikitext: str) -> NormalizedText: ...


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _remove_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _remove_balanced(
    text: str,
    open_marker: str,
    close_marker: str,
    *,
    max_depth: int,
) -> tuple[str, tuple[str, ...]]:
    warnings: list[str] = []
    open_len = len(open_marker)
    close_len = len(close_marker)
    result: list[str] = []
    i = 0
    length = len(text)
    work = 0
    while i < length:
        if work > MAX_SCAN_CHARS:
            warnings.append(f"Scanner work limit exceeded removing {open_marker!r} blocks")
            result.append(text[i:])
            break
        work += 1
        start = text.find(open_marker, i)
        if start == -1:
            result.append(text[i:])
            break
        result.append(text[i:start])
        depth = 1
        pos = start + open_len
        while pos < length and depth > 0:
            work += 1
            if work > MAX_SCAN_CHARS:
                warnings.append(f"Scanner work limit exceeded inside {open_marker!r} block")
                pos = length
                break
            next_open = text.find(open_marker, pos)
            next_close = text.find(close_marker, pos)
            if next_close == -1:
                warnings.append(f"Unclosed {open_marker!r} block")
                pos = length
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                if depth > max_depth:
                    warnings.append(f"Template nesting depth exceeded ({max_depth})")
                    pos = next_close + close_len
                    depth = 0
                    break
                pos = next_open + open_len
            else:
                depth -= 1
                pos = next_close + close_len
        i = pos
    return "".join(result), tuple(warnings)


def _remove_tag_blocks(text: str, tag: str) -> str:
    pattern = re.compile(rf"<\s*{tag}\b[^>]*>.*?</\s*{tag}\s*>", re.IGNORECASE | re.DOTALL)
    return pattern.sub("", text)


def _remove_self_closing_tags(text: str, tag: str) -> str:
    pattern = re.compile(rf"<\s*{tag}\b[^>]*/\s*>", re.IGNORECASE)
    return pattern.sub("", text)


def _remove_galleries(text: str) -> str:
    return _remove_tag_blocks(text, "gallery")


def _remove_math(text: str) -> str:
    text = _remove_tag_blocks(text, "math")
    text = re.sub(r"<math\b[^>]*/>", "", text, flags=re.IGNORECASE)
    return text


def _transform_internal_links(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if ":" in inner.split("|", 1)[0]:
            prefix = inner.split(":", 1)[0].strip().lower()
            if prefix in {"file", "image", "category", "categoría"}:
                return ""
        if "|" in inner:
            return inner.rsplit("|", 1)[-1]
        return inner

    return re.sub(r"\[\[([^\]]+)\]\]", repl, text)


def _transform_external_links(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        if not body:
            return ""
        parts = body.split(None, 1)
        if len(parts) == 2 and parts[0].startswith(("http://", "https://", "//")):
            return parts[1]
        if parts[0].startswith(("http://", "https://", "//")):
            return ""
        return body

    return re.sub(r"\[(https?://[^\]\s]+(?:\s+[^\]]+)?)\]", repl, text)


def _strip_headings(text: str) -> str:
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("=") and stripped.endswith("="):
            level = len(stripped) - len(stripped.lstrip("="))
            inner = stripped[level:-level].strip()
            lines.append(inner)
        else:
            lines.append(line)
    return "\n".join(lines)


def _strip_emphasis(text: str) -> str:
    text = re.sub(r"'{2,5}", "", text)
    return text


def _remove_interwiki_lines(text: str) -> str:
    lines: list[str] = []
    for line in text.split("\n"):
        if re.match(r"^[a-z]{2,3}:[^\s].*", line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines)


def _remove_magic_words(text: str) -> str:
    return re.sub(r"__([A-Z_]+)__", "", text)


def _collapse_whitespace(text: str) -> str:
    lines = [line.rstrip() for line in text.split("\n")]
    collapsed: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                collapsed.append("")
            continue
        blank_run = 0
        collapsed.append(line)
    result = "\n".join(collapsed).strip()
    return result


def _visible_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


class ArkPiWikipediaV1Normalizer:
    version = NORMALIZER_VERSION

    def normalize(self, wikitext: str) -> NormalizedText:
        warnings: list[str] = []
        text = _normalize_line_endings(wikitext)
        text = _remove_html_comments(text)
        text = _remove_tag_blocks(text, "ref")
        text = _remove_self_closing_tags(text, "ref")
        text, tmpl_warnings = _remove_balanced(text, "{{", "}}", max_depth=MAX_TEMPLATE_DEPTH)
        warnings.extend(tmpl_warnings)
        text, table_warnings = _remove_balanced(text, "{|", "|}", max_depth=MAX_TEMPLATE_DEPTH)
        warnings.extend(table_warnings)
        text = _remove_galleries(text)
        text = _remove_math(text)
        text = _remove_magic_words(text)
        text = _remove_interwiki_lines(text)
        text = _transform_internal_links(text)
        text = _transform_external_links(text)
        text = _strip_headings(text)
        text = _strip_emphasis(text)
        text = html.unescape(text)
        text = _collapse_whitespace(text)
        return NormalizedText(
            text=text,
            visible_chars=_visible_char_count(text),
            warnings=tuple(warnings),
        )


def redirect_text(target: str) -> str:
    return f"Redirect to {target}"
