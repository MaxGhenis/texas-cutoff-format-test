"""Turn the readers' findings into the two hash lists the build applies.

usage: .venv/bin/python scripts/reader_lists.py RESULTS.json [...] [screen-opus.md screen-sol.md]

A provenance tool: it needs the sealed runs and the readers' reports, which quote the evidence files
and so stay outside this repository. Each RESULTS.json is a list of reports. A report on a piece of
an evidence file has `unit` (such as "sol-3.part2") and `leaks` (each with `quote`, `category` and
`severity`): sentences the rules kept that the reader calls a forecast, odds, a statement of what
the election's result would do, or text the research run wrote. A report on the dropped sentences
has `unit` ("screen-opus" or "screen-sol") and `wrong_drops` (each with `file`, `rule`, `sentence`
and `verdict`): sentences the rules dropped that hold a fact and no forecast. A screen reader's own
log (`screen-opus.md`, `screen-sol.md`) also counts: each row "N | file | rule | VERDICT | ..." gives
a verdict on entry N of PRIVATE/audit-units/<log name>, the dropped-sentence list the reader read.

The script matches each finding to the sentences the screen judges (`evidence.trace`, rules only):

- a leak that matches a sentence the rules keep puts that sentence's key in
  `design/reader_removals.csv`, unless PRIVATE/reader/stays.tsv lists it (findings the registration's own rules
  allow: a candidate's own claim about policy, a fact of law);
- a wrong drop with verdict "wrong" that matches a sentence the rules drop puts its key in
  `design/reader_keeps.csv` ("borderline" verdicts stay dropped);
- a key in both lists goes: removal wins.

Removals apply in every file, so a sentence one reader marked goes wherever it recurs. The lists hold
keys, categories and file names; the sentences themselves go to PRIVATE/reader/.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cutoff import build, evidence, paths, sources  # noqa: E402

# Reported leaks that stay: PRIVATE/reader/stays.tsv lists a phrase each holds and the reason (a fact
# of law, a headline about past acts, a candidate's own claim about policy). The phrases quote the
# evidence, so they stay private with it.
def stays() -> dict[str, str]:
    path = paths.PRIVATE / "reader" / "stays.tsv"
    with path.open() as f:
        return {r["phrase"]: r["reason"] for r in csv.DictReader(f, delimiter="\t")}


_HEADER = re.compile(r"^\[\d+\]\s+(?:Page|Search results?|Extract):\s*")
_UNIT = re.compile(r"((?:opus|sol)-\d+)\.part\d+")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def matches(quote: str, pool: list[str]) -> list[str]:
    """The sentences in `pool` a reader's quote names: the quote sits in the sentence, the sentence
    makes up at least half of the quote (readers sometimes quoted two at once), or they share a long
    opening (readers cut long quotes at about 300 characters)."""
    q = norm(_HEADER.sub("", norm(quote).lstrip("-• ").strip()))
    if len(q) < 12:
        return []
    out = []
    for u in pool:
        n = norm(u)
        if q in n or (len(n) >= 25 and 2 * len(n) >= len(q) and n in q) or (len(q) >= 80 and n.startswith(q[:80])):
            out.append(u)
    return out


_ROW = re.compile(r"^(\d+)\s*\|\s*((?:opus|sol)-\d+)\s*\|\s*([a-z_]+)\s*\|\s*([A-Z][A-Z0-9]*)\b")
_LISTED = re.compile(r"^- \[[^\]]*\]\s?")
VERDICTS = {"W": "wrong", "WRONG": "wrong", "B": "borderline", "BORDERLINE": "borderline",
            "R": "right", "R0": "right", "RIGHT": "right"}  # fmt: skip


def screen_log(path: Path) -> dict:
    """A screen reader's log as a report with `wrong_drops`: each row's verdict on the sentence at that
    line of the unit file it read. A row given twice keeps its last verdict."""
    unit: list[str] = []  # one entry per "- [file | rule] sentence"; a sentence can run over lines
    for line in (paths.PRIVATE / "audit-units" / path.name).read_text().splitlines():
        if _LISTED.match(line) or not unit:
            unit.append(line)
        else:
            unit[-1] += "\n" + line
    rows: dict[int, dict] = {}
    for line in path.read_text().splitlines():
        m = _ROW.match(line.strip())
        if not m or m.group(4) not in VERDICTS:
            continue
        n = int(m.group(1))
        listed = unit[n - 1]
        if f"[{m.group(2)} |" not in listed:
            raise SystemExit(f"{path.name} row {n} names {m.group(2)}, but entry {n} of the unit reads {listed[:60]!r}")
        rows[n] = {"file": m.group(2), "rule": m.group(3), "verdict": VERDICTS[m.group(4)],
                   "sentence": _LISTED.sub("", listed)}  # fmt: skip
    return {"unit": path.stem, "wrong_drops": [rows[n] for n in sorted(rows)]}


def to_csv(columns: list[str], rows: list[dict], delimiter=",") -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n", delimiter=delimiter)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv=None) -> int:
    files = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    if not files:
        print(__doc__)
        return 2
    reports = [r for f in files if f.suffix == ".json" for r in json.loads(f.read_text()) if isinstance(r, dict)]
    reports += [screen_log(f) for f in files if f.suffix == ".md"]
    for rep in reports:
        if rep.get("unit", "").startswith("screen-"):
            tally = {}
            for d in rep.get("wrong_drops", []):
                tally[d["verdict"]] = tally.get(d["verdict"], 0) + 1
            print(f"{rep['unit']}: {sum(tally.values())} verdicts {tally}")
    trace = {}
    for label in sources.LABELS:
        items, _ = build.items_for(label)
        trace[label] = evidence.trace(items)  # rules only: (stay, go)

    allowed_phrases = stays()
    removals: dict[str, dict] = {}
    covered = allowed = lost = 0
    unmatched: list[str] = []
    for rep in reports:
        m = _UNIT.search(str(rep.get("unit", "")))
        if not m or "leaks" not in rep:
            continue
        label = m.group(1)
        stay, go = trace[label]
        for leak in rep["leaks"]:
            if any(phrase in leak["quote"] for phrase in allowed_phrases):
                allowed += 1
                continue
            if leak["category"] == "run_text" and norm(leak["quote"])[:1] in ('"', "{", "["):
                covered += 1  # a script's printed values: `evidence.tool_strings` now drops them
                continue
            hit = matches(leak["quote"], stay)
            if hit:
                for u in hit:
                    rec = removals.setdefault(
                        evidence.sentence_key(u), {"category": leak["category"], "severity": leak["severity"], "text": u}
                    )
                    if leak["severity"] == "high":
                        rec["severity"] = "high"
            elif matches(leak["quote"], [u for _, u in go]):
                covered += 1
            else:
                lost += 1
                unmatched.append(f"{label}: {leak['category']}: {norm(leak['quote'])[:70]}")
    for key, rec in removals.items():  # a removal applies wherever the sentence recurs
        rec["files"] = [label for label in sources.LABELS if any(evidence.sentence_key(u) == key for u in trace[label][0])]

    keeps: dict[str, dict] = {}
    still = moot = 0
    for rep in reports:
        for drop in rep.get("wrong_drops", []):
            label = drop["file"].strip()
            if label not in trace or drop["verdict"] != "wrong":
                still += drop["verdict"] != "wrong"
                continue
            stay, go = trace[label]
            pool = [u for reason, u in go if reason in evidence.SCREEN]
            hit = matches(drop["sentence"], pool)
            if not hit:
                moot += 1  # the revised rules no longer drop it, or a whole-item rule took its item
                continue
            for u in hit:
                key = evidence.sentence_key(u)
                if key not in removals:
                    keeps.setdefault(key, {"rule": evidence.screen_reason(u), "text": u, "files": []})
    for key, rec in keeps.items():
        rec["files"] = [label for label in sources.LABELS if any(evidence.sentence_key(u) == key for _, u in trace[label][1])]

    paths.DESIGN.mkdir(exist_ok=True)
    rem_rows = [
        {"key": k, "category": r["category"], "severity": r["severity"], "files": " ".join(r["files"])}
        for k, r in sorted(removals.items())
    ]
    keep_rows = [{"key": k, "rule": r["rule"], "files": " ".join(r["files"])} for k, r in sorted(keeps.items())]
    (paths.DESIGN / "reader_removals.csv").write_text(to_csv(["key", "category", "severity", "files"], rem_rows))
    (paths.DESIGN / "reader_keeps.csv").write_text(to_csv(["key", "rule", "files"], keep_rows))
    private = paths.PRIVATE / "reader"
    private.mkdir(parents=True, exist_ok=True)
    (private / "removals.tsv").write_text(
        to_csv(["key", "category", "severity", "text"], [{"key": k, "category": r["category"], "severity": r["severity"], "text": r["text"].replace("\t", " ")} for k, r in sorted(removals.items())], "\t")
    )
    (private / "keeps.tsv").write_text(
        to_csv(["key", "rule", "text"], [{"key": k, "rule": r["rule"], "text": r["text"].replace("\t", " ")} for k, r in sorted(keeps.items())], "\t")
    )
    print(f"removals: {len(removals)} sentences ({covered} reported leaks already go by rule; {allowed} stay by rule; {lost} unmatched)")
    print(f"keeps: {len(keeps)} sentences ({moot} reported wrong drops no longer dropped; {still} verdicts of right or borderline leave theirs dropped)")
    for line in unmatched:
        print("  unmatched:", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
