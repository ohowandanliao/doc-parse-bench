from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.repetition import audit_repetition, detect_repetition


def test_character_loop_is_detected_without_newlines():
    hits = detect_repetition("Intro " + "varepsilon'" * 60)
    hit = next(h for h in hits if h["kind"] == "character_loop")
    assert hit["unit"] == "varepsilon'" and hit["repeats"] == 60
    assert hit["start"] == 6


def test_repeated_lines_include_blank_separators_but_exclude_short_natural_repetition():
    hits = detect_repetition("intro\n" + "吴冰冰\n\n" * 50)
    hit = next(h for h in hits if h["kind"] == "identical_lines")
    assert hit["repeats"] == 50 and hit["line_start"] == 2
    assert not detect_repetition("page header\n" * 3)
    assert not detect_repetition("-" * 300)


def test_raw_empty_block_loops_and_evaluated_output_are_reported_separately(tmp_path):
    original = tmp_path / "original/Unlimited-OCR-2/doc.json"
    raw = "<PAGE>" + "<BLOCK>header[132,132,132,132]<FORK>\n" * 30
    write_json(
        original,
        {
            "stem": "doc",
            "n_pages": 2,
            "raw": raw,
            "pages": [{"page": 1, "md": "", "blocks": []}],
            "meta": {"finish": "length"},
        },
    )
    evaluated = tmp_path / "evaluated/Unlimited-OCR-2/OmniDocBench/doc__p0001.md"
    evaluated.parent.mkdir(parents=True)
    evaluated.write_text("")
    result = audit_repetition(tmp_path / "original", tmp_path / "audit", tmp_path / "evaluated")
    model = result["models"]["Unlimited-OCR-2"]
    assert model["original_candidate_pages"] == 1
    assert model["evaluation_candidate_pages"] == 0
    evidence = read_json(tmp_path / "audit/audit.json")["models"]["Unlimited-OCR-2"]["findings"][0]
    assert (tmp_path / "audit" / evidence["evidence"]).read_text() == raw.removeprefix("<PAGE>")
    assert read_json(original)["raw"] == raw
