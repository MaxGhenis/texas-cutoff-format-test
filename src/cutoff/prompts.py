"""Render a context's prompt: Subfleet's headless marker, one of the three registered briefs, its
scenario, and an evidence file.

The 16 evidence files and 13 brief variants (the grid, and six shares in each isolated arm) make 208
distinct prompts. Every replicate of a context sends the same bytes.
"""

from __future__ import annotations

from . import paths
from .jump import CELLS

ARMS = ("grid", "alone", "told")
# Subfleet puts a note on headless running ahead of every Claude prompt unless the prompt holds this
# marker (its contract C-6.7), and sends a Codex prompt as it stands. Every prompt opens with the
# marker, so both models read the same bytes and nothing comes before the brief.
HEADLESS_MARKER = "<!-- subfleet:headless -->"
EVIDENCE_OPEN = "=== Evidence file begins ==="
EVIDENCE_CLOSE = "=== Evidence file ends ==="
PLACEHOLDERS = ("<<KEY>>", "<<SHARE>>", "<<WINNER>>", "<<EVIDENCE>>")


def share_text(cell: float) -> str:
    return f"{cell:g}"


def cell_key(cell: float) -> str:
    return f"dem_{cell:.1f}"


def winner(cell: float) -> str:
    if cell == 50.0:
        raise ValueError("no cell sits at the threshold")
    return "Hinojosa" if cell > 50.0 else "Abbott"


def brief(arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(arm)
    return (paths.BRIEFS / f"{arm}.md").read_text()


def render(arm: str, cell: float | None, evidence: str) -> str:
    text = brief(arm)
    if arm == "grid":
        if cell is not None:
            raise ValueError("the grid takes no cell")
    else:
        if cell not in CELLS:
            raise ValueError(f"{cell} is not a registered cell")
        text = text.replace("<<KEY>>", cell_key(cell)).replace("<<SHARE>>", share_text(cell))
        text = text.replace("<<WINNER>>", winner(cell))
    if any(p in text for p in PLACEHOLDERS[:3]):
        raise ValueError(f"{arm}: a scenario placeholder survived")
    if text.count("<<EVIDENCE>>") != 1:
        raise ValueError(f"{arm}: the brief must hold one evidence placeholder")
    if EVIDENCE_OPEN in evidence or EVIDENCE_CLOSE in evidence:
        raise ValueError("the evidence holds a line that marks where the evidence begins or ends")
    body = text.replace("<<EVIDENCE>>", f"{EVIDENCE_OPEN}\n{evidence.rstrip()}\n{EVIDENCE_CLOSE}")
    return f"{HEADLESS_MARKER}\n{body}"


def prompt_id(file: str, arm: str, cell: float | None) -> str:
    return f"{file}__grid" if arm == "grid" else f"{file}__{arm}__{cell_key(cell)}"


def variants() -> list[tuple[str, float | None]]:
    """The 13 (arm, cell) variants, in registered order."""
    return [("grid", None)] + [(arm, c) for arm in ("alone", "told") for c in CELLS]
