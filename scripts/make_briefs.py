"""Write the three registered briefs (briefs/grid.md, alone.md, told.md) from the sealed Texas brief.

usage: .venv/bin/python scripts/make_briefs.py [--check]

The sealed brief is prompts/forecaster.md in the public Texas repository (SHA-256 e58beb9f…, the
prompt every sealed run received). Each brief here copies its three question blocks and its whole
"Context" section word for word, and changes only what a closed context with an evidence file needs:

- the opening and rule 1 say there are no tools and point to the evidence file;
- the rules drop what the dropped questions needed (the vote-share and turnout forms, baselines);
- the Output section drops `research_summary`, since no context researches;
- the grid keeps the sealed rules on cells (4, 5) and on reasoning (7). The two isolated briefs give
  one scenario and ask how it bears on each forecast; the told brief adds one sentence naming the six
  shares that separate conversations answer, and nothing else;
- the isolated briefs ask the context to restate its scenario after its forecasts.

Placeholders: <<KEY>> (dem_50.5), <<SHARE>> (50.5), <<WINNER>> (Hinojosa) and <<EVIDENCE>>.
`--check` exits 1 if the committed briefs differ from what this script writes.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cutoff import paths  # noqa: E402
from cutoff.jump import KEYS, QUESTIONS, QUANTILES  # noqa: E402

SEALED_SHA256 = "e58beb9f1f37a8a18270f74ae665485bf36ace8ea6d37de296b84220ee709237"
GRID_FORECASTS = "- Forecasts: `dem_44.0`, `dem_47.0`, `dem_49.5`, `dem_50.5`, `dem_53.0`, `dem_56.0`."


def sealed_brief() -> str:
    text = (paths.PUBLIC_TEXAS / "prompts" / "forecaster.md").read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != SEALED_SHA256:
        raise SystemExit(f"the sealed brief's SHA-256 is {digest}, not {SEALED_SHA256}")
    return text


def question_block(text: str, qid: str) -> str:
    """The sealed brief's block for one question, from its ### heading to the next heading."""
    m = re.search(rf"^### `{qid}`:.*?(?=^#{{2,3}} )", text, re.S | re.M)
    if not m:
        raise SystemExit(f"no block for {qid}")
    block = m.group(0).rstrip() + "\n"
    if GRID_FORECASTS not in block:
        raise SystemExit(f"{qid}: the sealed block lacks the six-cell forecasts line")
    return block


def context_section(text: str) -> str:
    m = re.search(r"^## Context\n.*?(?=^## Response template)", text, re.S | re.M)
    if not m:
        raise SystemExit("no Context section")
    return m.group(0).rstrip() + "\n"


INTRO = """# Forecasting brief: the 2026 Texas governor's race and data centers

You are one of several forecasters working independently on the same questions. Forecast as of
2026-11-03, before Texas polls closed: use what was known then, and nothing about any results. You
have no web access here. In its place, the evidence file near the end of this brief holds what an
earlier research session's web tools returned on 2026-11-03, before polls closed. Reason from it, from
base rates and from the facts in this brief, and give your own numbers.
"""

RULES_SHARED_TOP = """## Rules

1. Work from this brief and its evidence file. Do not use any tool: no web search, no files, no code.
2. Do not use vote counts or results of the 2026-11-03 election, even partial ones; turnout figures
   from early voting are fine. If you know of any count, say so in `forecaster.notes`.
3. Every number is an absolute level in the unit stated (percent, probabilities), never a ratio or a
   change.
"""

RULES_GRID_CELLS = """4. Each forecast is conditional on its scenario. A *cell* such as `dem_50.5` means: the official canvass
   gives Gina Hinojosa exactly that share of the two-party vote for governor (Hinojosa's votes divided by
   Hinojosa's plus Greg Abbott's). At 50.5% she wins; at 49.5% Abbott does. Everything else about the
   world is whatever you think is consistent with that result.
5. Every question is asked at all six cells: 44%, 47%, 49.5%, 50.5%, 53% and 56%.
"""

RULES_ONE_SCENARIO = """4. Your forecasts are conditional on one scenario: the official canvass gives Gina Hinojosa exactly
   <<SHARE>>% of the two-party vote for governor (Hinojosa's votes divided by Hinojosa's plus Greg
   Abbott's), so <<WINNER>> wins. Everything else about the world is whatever you think is consistent
   with that result.
"""

RULE5_ALONE = """5. Every question is forecast under that scenario, under the key `<<KEY>>`.
"""

RULE5_TOLD = """5. This study asks the same questions in separate conversations, each given one of six shares: 44%,
   47%, 49.5%, 50.5%, 53% and 56%. Each conversation sees only its own. Every question here is
   forecast under yours, under the key `<<KEY>>`.
"""

RULE6 = """6. Quantities take five quantiles (p05, p25, p50, p75, p95): your 5th percentile, quartiles, median and
   95th percentile. Quantiles must not decrease and must lie within the stated bounds.
"""

RULE7_GRID = """7. Keep each question's `reasoning` to a few sentences: the base rate, the main mechanism, and what
   moves the forecast across cells. List the URLs you relied on in `sources`.
"""

RULE7_ONE = """7. Keep each question's `reasoning` to a few sentences: the base rate, the main mechanism, and how the
   scenario bears on the forecast. List the URLs you relied on in `sources`.
"""

RULE8 = """8. Before you forecast, record in `forecaster.prior_context` anything in your context other than this
   brief (system prompt, memory, instructions, files, earlier conversation) that mentions the Texas
   governor's race, data centers, or forecasts of these questions. Quote it, or write "none".
"""

OUTPUT_GRID = """## Output

Your final message must be the completed template below as a single JSON object in one ```json fenced
block, with every null replaced. Put your model name in `forecaster.model`. Use exactly the template's
keys: add none and rename none. Nothing after the block.
"""

OUTPUT_ONE = """## Output

Your final message must be the completed template below as a single JSON object in one ```json fenced
block, with every null replaced. Put your model name in `forecaster.model`. After your forecasts, in
`scenario`, restate the scenario you forecast under: Hinojosa's share as a number, and the surname of
the candidate who wins. Use exactly the template's keys: add none and rename none. Nothing after the
block.
"""

QUESTIONS_GRID = """## The questions

The governor's race sets the cells. Each question, on the Senate race and on what the state does about
data centers, is forecast at each cell. Read every question before forecasting any, so your answers
cohere.
"""

QUESTIONS_ONE = """## The questions

The governor's race sets the scenario. Each question, on the Senate race and on what the state does
about data centers, is forecast under it. Read every question before forecasting any, so your answers
cohere.
"""

EVIDENCE = """## Evidence file

<<EVIDENCE>>
"""


def value_template(qid: str) -> dict:
    if qid == "senate_dem_share":
        return {f"p{round(q * 100):02d}": None for q in QUANTILES}
    return {"p": None}


def response_template(keys) -> str:
    nodes = {
        qid: {"forecasts": {k: value_template(qid) for k in keys}, "reasoning": None, "sources": []}
        for qid in QUESTIONS
    }
    obj = {"forecaster": {"model": None, "prior_context": None, "notes": None}, "nodes": nodes}
    if len(keys) == 1:
        obj["scenario"] = {"hinojosa_share": None, "winner": None}
    return "## Response template\n\n```json\n" + json.dumps(obj, indent=1) + "\n```\n"


def build(arm: str, sealed: str) -> str:
    one = arm != "grid"
    blocks = [question_block(sealed, q) for q in QUESTIONS]
    if one:
        blocks = [b.replace(GRID_FORECASTS, "- Forecasts: `<<KEY>>`.") for b in blocks]
    rules = RULES_SHARED_TOP
    if one:
        rules += RULES_ONE_SCENARIO + (RULE5_TOLD if arm == "told" else RULE5_ALONE) + RULE6 + RULE7_ONE + RULE8
    else:
        rules += RULES_GRID_CELLS + RULE6 + RULE7_GRID + RULE8
    parts = [
        INTRO,
        rules,
        OUTPUT_ONE if one else OUTPUT_GRID,
        QUESTIONS_ONE if one else QUESTIONS_GRID,
        "## The vote\n\n" + blocks[0],
        "## What the state does about data centers\n\n" + blocks[1] + "\n" + blocks[2],
        context_section(sealed),
        EVIDENCE,
        response_template(["<<KEY>>"] if one else list(KEYS)),
    ]
    return "\n".join(p.rstrip() + "\n" for p in parts)


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    sealed = sealed_brief()
    bad = 0
    for arm in ("grid", "alone", "told"):
        text = build(arm, sealed)
        path = ROOT / "briefs" / f"{arm}.md"
        if check:
            if not path.exists() or path.read_text() != text:
                print(f"{path.relative_to(ROOT)} differs from what scripts/make_briefs.py writes")
                bad = 1
        else:
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)} ({len(text):,} characters)")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
