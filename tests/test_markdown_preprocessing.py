import pytest

from doc_parse_bench.cli import main
from doc_parse_bench.compatibility.cleaning import process_chart_details
from doc_parse_bench.io import read_json


@pytest.mark.parametrize(
    ("flags", "replace_images", "expand_details"),
    [
        ([], False, False),
        (["--replace-images"], True, False),
        (["--expand-details"], False, True),
        (["--replace-images", "--expand-details"], True, True),
    ],
)
def test_markdown_preparation_keeps_image_and_chart_choices_independent(
    tmp_path, flags, replace_images, expand_details
):
    source = tmp_path / "raw"
    source.mkdir()
    raw = (
        "# Heading\n\n"
        "![photo](data:image/png;base64,AAAA)\n\n"
        '<img src="data:image/png;base64,BBBB" />\n\n'
        "![chart](page1_100_200_900_800.jpg)\n\n"
        "<details><summary>bar</summary>\n\n"
        "| Year | Value |\n| --- | --- |\n| 2025 | 42 |\n</details>\n"
    )
    (source / "doc.md").write_text(raw)
    output = tmp_path / "prepared"
    main(["prepare-markdown", str(source), str(output), *flags])
    result = (output / "doc.md").read_text()
    assert (source / "doc.md").read_text() == raw
    assert result.startswith("# Heading")
    assert "| 2025 | 42 |" in result
    assert ("data:image/png;base64,AAAA" not in result) is replace_images
    assert ("data:image/png;base64,BBBB" not in result) is replace_images
    assert ("<details>" not in result) is expand_details
    assert ("page1_100_200_900_800.jpg" not in result) is expand_details
    if not flags:
        assert result == raw
    manifest = read_json(output / "manifest.json")
    assert manifest["replace_embedded_images"] is replace_images
    assert manifest["expand_chart_details"] is expand_details


def test_legacy_preparation_allows_placeholder_only_override(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    raw = (
        "![photo](data:image/png;base64,AAAA)\n\n"
        "<details><summary>note</summary>keep for review</details>"
    )
    (source / "doc.md").write_text(raw)
    output = tmp_path / "prepared"
    main(["prepare-legacy", str(source), str(output), "--no-expand-details"])
    result = (output / "doc.md").read_text()
    assert "data:image" not in result
    assert "<details><summary>note</summary>keep for review</details>" in result


def test_details_function_preserves_base64_references_outside_chart_content():
    image = "![photo](data:image/png;base64,AAAA)"
    text = image + "\n<details><summary>note</summary>hidden</details>"
    assert process_chart_details(text) == image
