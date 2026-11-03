from dataclasses import asdict

from doc_parse_bench.compatibility.cleaning import CleaningOptions, normalize_markdown
from doc_parse_bench.profiles import resolve_options


def test_profiles_assign_defaults_and_overrides_are_independent():
    standard = resolve_options("standard")
    legacy = resolve_options("legacy")
    assert standard.figure_metric and standard.relation_metrics
    assert not standard.replace_embedded_images and legacy.replace_embedded_images
    assert not standard.expand_chart_details and legacy.expand_chart_details
    changed = resolve_options("standard", {"merge_context": True, "formula_cdm": None})
    assert changed.merge_context and not changed.formula_cdm
    assert not resolve_options("standard").merge_context
    differences = {key for key, value in asdict(standard).items() if asdict(legacy)[key] != value}
    assert differences == {"replace_embedded_images", "expand_chart_details"}


def test_legacy_preprocessing_does_not_disable_document_relation_scoring():
    options = resolve_options("legacy", {"merge_context": True})
    assert options.merge_context and options.relation_metrics and options.figure_metric


def test_image_replacement_can_be_disabled_independently_of_details_cleanup():
    text = "![x](data:image/png;base64,AAAA)\n\n<details><summary>note</summary>hidden</details>"
    result = normalize_markdown(text, CleaningOptions(False, True))
    assert "data:image/png;base64,AAAA" in result
    assert "<details>" not in result
    assert normalize_markdown(text, CleaningOptions(False, False)) == text
