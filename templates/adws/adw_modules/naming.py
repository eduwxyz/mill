"""Turning a human title into the directory name the run will live under.

Slugging is arithmetic over a string — a known operation, so it is code, not an
agent (SKILL.md hard rule 8). Handing it to a model would buy nothing a
`re.sub()` does not already do, and would introduce the one failure this must
not have: two stages disagreeing about where a feature's files are.

`adw_spec` slugs the feature title, `adw_tickets` slugs the spec's filename, and
they must land on the same `.scratch/<feature>/` either way.
"""

from __future__ import annotations

import re

SLUG_MAX = 60


def slug(title: str) -> str:
    """`Partial results over hard failure` → `partial-results-over-hard-failure`.

    Truncated to `SLUG_MAX` so a long title cannot produce a path the filesystem
    refuses, and never empty — a title of pure punctuation still needs somewhere
    to go.
    """
    text = title.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:SLUG_MAX].rstrip("-") or "decision"
