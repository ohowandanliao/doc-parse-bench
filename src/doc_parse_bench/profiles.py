"""Two named evaluation modes with complete defaults and explicit overrides."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class EvaluationOptions:
    replace_embedded_images: bool
    expand_chart_details: bool
    merge_context: bool
    allow_missing: bool
    formula_cdm: bool
    figure_metric: bool
    relation_metrics: bool
    exact_teds: bool = False


PROFILES = {
    "standard": EvaluationOptions(False, False, False, True, False, True, True, True),
    "legacy": EvaluationOptions(True, True, False, True, False, False, False),
}


def resolve_options(profile: str, overrides: dict | None = None) -> EvaluationOptions:
    if profile not in PROFILES:
        raise ValueError(f"未知评测模式：{profile}；可选 standard / legacy")
    supplied = {key: value for key, value in (overrides or {}).items() if value is not None}
    options = replace(PROFILES[profile], **supplied)
    if profile == "legacy" and options.merge_context:
        raise ValueError("历史 Markdown 缺少页面关系，不能启用跨页推断")
    return options
