"""Image/details normalization absorbed from the historical pipeline.

The two switches are independently configurable in code. Named evaluation profiles
assign their defaults; changing them produces an explicitly recorded override.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CleaningOptions:
    replace_embedded_images: bool = True
    expand_chart_details: bool = True


# Match ![alt](data:image/...;base64,...)  — markdown image syntax
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^;]+;base64,[^)]+\)")

# Match <img src="data:image/...;base64,..." ... >  — HTML image tag
_HTML_IMAGE_RE = re.compile(r'<img\s[^>]*src="data:image/[^;]+;base64,[^"]+"[^>]*>')

PLACEHOLDER = "![image](this is a image)"


def replace_base64_images(text: str) -> tuple[str, int]:
    """
    Replace all base64 image references in *text* with PLACEHOLDER.
    Returns (replaced_text, count).
    """
    count = 0

    # 1. Markdown format
    matches = list(_MD_IMAGE_RE.finditer(text))
    count += len(matches)
    for m in reversed(matches):
        text = text[: m.start()] + PLACEHOLDER + text[m.end() :]

    # 2. HTML format
    matches = list(_HTML_IMAGE_RE.finditer(text))
    count += len(matches)
    for m in reversed(matches):
        text = text[: m.start()] + PLACEHOLDER + text[m.end() :]

    return text, count


KEYWORDS = ["bar", "line", "pie", "bar_line"]


def has_markdown_table(content):
    """Check if content contains a markdown table (| row followed by |---| row)."""
    lines = content.strip().split("\n")
    for i, line in enumerate(lines):
        if "|" in line and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if re.match(r"^\|?[\s:]*---[\s\-:|]*$", nxt):
                return True
    return False


def process_content(content, replace_embedded_images=True):
    # Pattern: ![alt](url) + <details><summary>...</summary>...</details>
    paired_re = re.compile(
        r"!\[([^\]]*)\]\(([^)]*)\)\s*<details>\s*<summary>([^<]*)</summary>\s*(.*?)</details>",
        re.DOTALL | re.IGNORECASE,
    )

    def paired_replacer(m):
        summary = m.group(3)
        inner = m.group(4)

        branch_a = any(kw in summary.lower() for kw in KEYWORDS) or has_markdown_table(inner)

        if branch_a:
            return inner
        else:
            return f"![{m.group(1)}]({m.group(2)})"

    # Pass 1: handle image + details pairs
    content = paired_re.sub(paired_replacer, content)

    # Pass 2: remove remaining standalone <details> blocks
    standalone_re = re.compile(
        r"<details>\s*<summary>[^<]*</summary>\s*.*?</details>",
        re.DOTALL,
    )
    content = standalone_re.sub("", content)

    # Pass 3: replace base64 inline images with unified placeholder
    # 匹配 ![alt](data:image/...;base64,...) 格式
    base64_re = re.compile(
        r"!\[([^\]]*)\]\(data:image/[^;]+;base64,[^)]+\)",
        re.IGNORECASE,
    )
    if replace_embedded_images:
        content = base64_re.sub(r"![image](images/aipaas.jpg)", content)

    return content


def normalize_markdown(text: str, options: CleaningOptions = CleaningOptions()) -> str:
    if options.replace_embedded_images:
        text, _ = replace_base64_images(text)
    if options.expand_chart_details:
        text = process_content(text, replace_embedded_images=options.replace_embedded_images)
    return text
