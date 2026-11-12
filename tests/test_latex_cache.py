from types import SimpleNamespace

from doc_parse_bench.backends.latex_cache import install


def test_success_cache_preserves_results_timeout_keys_and_failure_context():
    calls = []

    def original(latex, timeout=None):
        calls.append((latex, timeout, module.page))
        return None if latex == "broken" else f"converted:{latex}"

    module = SimpleNamespace(
        _latex_to_text_with_timeout=original,
        _resolve_timeout=lambda timeout: 20 if timeout is None else timeout,
        page="page1",
    )
    cache = install(module)
    convert = module._latex_to_text_with_timeout
    assert convert(r"\wedge") == "converted:\\wedge"
    module.page = "page2"
    assert convert(r"\wedge") == "converted:\\wedge"
    assert len(calls) == 1
    assert convert(r"\wedge", timeout=5) == "converted:\\wedge"
    assert calls[-1] == (r"\wedge", 5, "page2")
    assert convert("broken") is None
    module.page = "page3"
    assert convert("broken") is None
    assert calls[-2:] == [("broken", 20, "page2"), ("broken", 20, "page3")]
    assert cache.cache_info().hits == 1


def test_success_cache_evicts_and_preserves_empty_success():
    calls = []

    def original(latex, timeout=None):
        calls.append(latex)
        return latex

    module = SimpleNamespace(
        _latex_to_text_with_timeout=original, _resolve_timeout=lambda timeout: timeout
    )
    install(module, maxsize=1)
    assert module._latex_to_text_with_timeout("") == ""
    assert module._latex_to_text_with_timeout("") == ""
    assert calls == [""]
    assert module._latex_to_text_with_timeout("next") == "next"
    assert module._latex_to_text_with_timeout("") == ""
    assert calls == ["", "next", ""]
