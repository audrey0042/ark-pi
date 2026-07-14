"""Tests for wikitext normalization."""

from ark_pi.corpus.wikitext import ArkPiWikipediaV1Normalizer, NORMALIZER_VERSION


def test_normalizer_version() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    assert normalizer.version == NORMALIZER_VERSION


def test_internal_link_label_retained() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("See [[Target page|display label]] here.")
    assert "display label" in result.text
    assert "[[" not in result.text


def test_internal_link_without_label() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("See [[Target page]] here.")
    assert "Target page" in result.text


def test_external_link_label_retained() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("Visit [https://example.test Example label] today.")
    assert "Example label" in result.text
    assert "https://" not in result.text


def test_nested_templates_removed() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    source = "Before {{outer|{{inner|noise}}|tail}} after"
    result = normalizer.normalize(source)
    assert "Before" in result.text
    assert "after" in result.text
    assert "{{" not in result.text
    assert "inner" not in result.text


def test_references_removed() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("Text <ref>citation</ref> more")
    assert "citation" not in result.text
    assert "Text" in result.text


def test_table_removed() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    source = "Lead\n{| class=\"wikitable\"\n|-\n|Cell\n|}\nTail"
    result = normalizer.normalize(source)
    assert "Cell" not in result.text
    assert "Lead" in result.text
    assert "Tail" in result.text


def test_headings_preserved() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("== Section title ==\nBody")
    assert "Section title" in result.text
    assert "==" not in result.text


def test_html_entities_decoded() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("Tom &amp; Jerry")
    assert "Tom & Jerry" in result.text


def test_whitespace_normalization_deterministic() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    source = "Line one\r\n\r\n\r\nLine two   \r\n"
    first = normalizer.normalize(source)
    second = normalizer.normalize(source)
    assert first.text == second.text
    assert first.visible_chars == second.visible_chars


def test_file_and_category_links_removed() -> None:
    normalizer = ArkPiWikipediaV1Normalizer()
    result = normalizer.normalize("[[File:Example.png|thumb]] [[Category:Hidden]] prose")
    assert "prose" in result.text
    assert "Example.png" not in result.text
    assert "Category" not in result.text
