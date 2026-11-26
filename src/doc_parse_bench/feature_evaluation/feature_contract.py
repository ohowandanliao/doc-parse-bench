"""Shared feature names and capture pairs for PDF2Text evaluation."""

FEATURE_GT_VERSION = "legacy-129-feature-v3"
FEATURES = ("appendix", "header_footer", "image", "chart")
PAIRS = {
    "appendix": ("appendix", "off"),
    "header_footer": ("header_footer", "off"),
    "image": ("image", "controls/image_off"),
    "chart": ("chart", "image"),
}
