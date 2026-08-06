"""Style registry — maps style_id to a system-prompt description.

A style is just a markdown file with:
  - visual guidelines (colors / sizes / rhythm)
  - one few-shot code example

The agent receives the chosen style's markdown appended to the base
system prompt. We don't hard-code styles in Python — adding a new style
is a matter of dropping a new .md file in ``shared/prompts/styles/``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_STYLES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "shared"
    / "prompts"
    / "styles"
)
_BASE_FILE = _STYLES_DIR / "base.md"

# Canonical list — keep in sync with frontend dropdown.
STYLE_IDS: tuple[str, ...] = ("3b1b", "minimal", "academic")
DEFAULT_STYLE_ID = "3b1b"


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    description: str  # full markdown body (base + style-specific)


# Friendly labels (used by frontend).
STYLE_LABELS: dict[str, str] = {
    "3b1b": "3Blue1Brown（深色鲜艳）",
    "minimal": "Minimal（深色极简）",
    "academic": "Academic（明亮学术）",
}


def load_style(style_id: str) -> Style:
    """Load a style by id; unknown ids fall back to ``DEFAULT_STYLE_ID``.

    Raises FileNotFoundError only if the base file is missing — a
    programming error, not a user error.
    """
    if not _BASE_FILE.exists():
        raise FileNotFoundError(f"base style file missing: {_BASE_FILE}")

    if style_id not in STYLE_IDS:
        style_id = DEFAULT_STYLE_ID

    style_file = _STYLES_DIR / f"{style_id}.md"
    if not style_file.exists():
        # Style file missing for an *allowed* id — also fall back.
        style_id = DEFAULT_STYLE_ID
        style_file = _STYLES_DIR / f"{style_id}.md"

    description = _BASE_FILE.read_text(encoding="utf-8") + "\n\n" + style_file.read_text(
        encoding="utf-8"
    )

    return Style(
        id=style_id,
        name=STYLE_LABELS.get(style_id, style_id),
        description=description,
    )


__all__ = [
    "Style",
    "load_style",
    "STYLE_IDS",
    "STYLE_LABELS",
    "DEFAULT_STYLE_ID",
]
