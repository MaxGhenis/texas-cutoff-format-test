"""The registered analysis. Every number comes from `outputs/answers.csv`, the passed contexts'
answers in points, and `design/reference.json`, the sealed runs' own jumps.

**Jumps.** For an evidence file, an answering family, an arm and a question, the cell mean is the
mean answer at a cell over that arm's contexts, and the jump is `jump.jump` of the six cell means. In
the grid arm that equals the mean of the contexts' own jumps. A signed jump is the jump times the
question's registered direction.

**Differences.** d(file, family) = signed jump in one arm minus signed jump in another. The pooled
difference of a file is the mean of d over the families that count (see the bridge). The estimate is
the mean of the files' pooled differences; its standard error is their standard deviation over the
square root of the number of files, with a t distribution on one fewer degrees of freedom. The file is
the unit: contexts within a file share its evidence.

**Tests.** For each difference: a two-sided test of zero, and an equivalence test against the
question's margin (two one-sided tests at 5%, which pass exactly when the 90% interval lies inside
plus or minus the margin). The two primary differences are alone minus grid on the ERCOT question and
on the special-session question; Holm's method adjusts their two p-values, for each kind of test. A
primary question with no pooled result enters Holm's adjustment with a p-value of 1.

**Bridge.** For each family and question: the mean, over that family's accepted sealed runs, of the
closed grid jump from the run's own evidence file, answered by the same family, minus the run's sealed
jump. The bridge holds when that mean lies within the margin. A family whose bridge fails on a
primary question drops out of that question's pooled differences; with no family left, the question
has no pooled result. Talarico's share, which takes no verdict, pools both families whatever its
bridge shows.

**What a paper's abstract reports** (`abstract_rule`): the research runs' jumps alone if both primary
verdicts read equivalent and, on both primary questions, the unadjusted 90% interval of told minus
grid lies inside the margin; otherwise those jumps beside the alone arm's pooled jumps from this test.

**When it runs.** The registered analysis runs once, when no context of the design stays due, live or
in review (`design_counts`, from the public tables). `main` labels any earlier run INTERIM. It also
sets the number of contexts a share it used beside the replicate rule's record and what the rule gives
on wave 1's answers now (`replicate_record`), so a skipped rule or an edited record shows.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict

import numpy as np
from scipy import stats

from . import design, paths, registration, sources, store
from .jump import DIRECTION, KEYS, QUESTIONS, jump

ARMS = ("grid", "alone", "told")
CONTRASTS = (("alone", "grid"), ("told", "grid"), ("told", "alone"))
PRIMARY_CONTRAST = ("alone", "grid")
ALPHA = 0.05


def load(path=None, max_replicate: int | None = None, strict: bool = False, wave: int | None = None) -> list[dict]:
    """The answer rows that count: replicates up to `max_replicate`; with `strict`, no repaired answer
    and none whose prior_context needed the reading."""
    path = path or paths.OUTPUTS / "answers.csv"
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            r["replicate"], r["wave"], r["value"] = int(r["replicate"]), int(r["wave"]), float(r["value"])
            if max_replicate is not None and r["replicate"] > max_replicate:
                continue
            if wave is not None and r["wave"] != wave:
                continue
            if strict and (r["repaired"] == "1" or r["prior_read"] == "1"):
                continue
            out.append(r)
    return out


def cell_values(rows: list[dict]) -> dict:
    """{(file, family, arm, question): {key: [each context's answer]}}."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[(r["file"], r["family"], r["arm"], r["question"])][r["key"]].append(r["value"])
    return out


def jumps(rows: list[dict]) -> dict:
    """{(file, family, arm, question): the jump of the six cell means}; a combination with an empty
    cell has no jump and is left out."""
    out = {}
    for combo, cells in cell_values(rows).items():
        if all(cells.get(k) for k in KEYS):
            out[combo] = jump([float(np.mean(cells[k])) for k in KEYS])
    return out


def interval(values, level: float) -> tuple[float, float]:
    v = np.asarray(values, dtype=float)
    n = len(v)
    half = stats.t.ppf(0.5 + level / 2, n - 1) * v.std(ddof=1) / math.sqrt(n)
    return float(v.mean() - half), float(v.mean() + half)


def paired(values, margin: float | None = None) -> dict:
    """The mean of per-file values with its t-based intervals and tests."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < 2:
        return {"n": n, "mean": float(v.mean()) if n else None}
    mean, sd = float(v.mean()), float(v.std(ddof=1))
    se = sd / math.sqrt(n)
    out = {"n": n, "mean": mean, "sd": sd, "se": se, "ci90": interval(v, 0.90), "ci95": interval(v, 0.95)}
    if se == 0:
        out["p_zero"] = 1.0 if mean == 0 else 0.0
        if margin is not None:
            out.update(margin=margin, p_equivalent=0.0 if abs(mean) < margin else 1.0, equivalent=abs(mean) < margin)
        return out
    out["p_zero"] = float(2 * stats.t.sf(abs(mean) / se, n - 1))
    if margin is not None:
        p_low = float(stats.t.sf((mean + margin) / se, n - 1))  # against: the mean lies at or below -margin
        p_high = float(stats.t.cdf((mean - margin) / se, n - 1))  # against: the mean lies at or above +margin
        out.update(margin=margin, p_equivalent=max(p_low, p_high))
        out["equivalent"] = -margin < out["ci90"][0] and out["ci90"][1] < margin
    return out


def holm(ps: list[float]) -> list[float]:
    """Holm's step-down adjusted p-values, in the order given."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adjusted, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = running
    return adjusted


def signed_jumps(js: dict) -> dict:
    return {k: v * DIRECTION[k[3]] for k, v in js.items()}


def bridge(js: dict, reference: dict) -> dict:
    """{family: {question: {mean, ci90, holds, files}}}: closed grid jump minus sealed jump, over the
    family's accepted runs."""
    out: dict = {}
    for fam in design.FAMILIES:
        out[fam] = {}
        for q in QUESTIONS:
            files = {}
            for label, run in reference["runs"].items():
                if run["family"] == fam and (label, fam, "grid", q) in js:
                    closed, sealed = js[(label, fam, "grid", q)], run["questions"][q]["jump"]
                    files[label] = {"closed": closed, "sealed": sealed, "difference": closed - sealed}
            rec = paired([f["difference"] for f in files.values()], design.MARGIN[q])
            expected = sum(run["family"] == fam for run in reference["runs"].values())
            rec["complete"] = len(files) == expected
            rec["holds"] = bool(rec["complete"] and rec.get("mean") is not None and abs(rec["mean"]) <= design.MARGIN[q])
            rec["files"] = files
            out[fam][q] = rec
    return out


def file_differences(sj: dict, q: str, hi: str, lo: str, families) -> dict[str, float]:
    """{file: the mean over `families` of signed jump in arm `hi` minus arm `lo`}, for the files where
    every family in `families` has both jumps."""
    out = {}
    for f in sources.LABELS:
        ds = [sj[(f, m, hi, q)] - sj[(f, m, lo, q)] for m in families if (f, m, hi, q) in sj and (f, m, lo, q) in sj]
        if families and len(ds) == len(families):
            out[f] = float(np.mean(ds))
    return out


def arm_levels(sj: dict, q: str, arm: str, families) -> dict[str, float]:
    out = {}
    for f in sources.LABELS:
        vs = [sj[(f, m, arm, q)] for m in families if (f, m, arm, q) in sj]
        if families and len(vs) == len(families):
            out[f] = float(np.mean(vs))
    return out


def contrasts(sj: dict, q: str, families) -> dict:
    out = {"families": list(families), "arms": {}, "differences": {}}
    for arm in ARMS:
        out["arms"][arm] = paired(list(arm_levels(sj, q, arm, families).values()))
    for hi, lo in CONTRASTS:
        d = file_differences(sj, q, hi, lo, families)
        rec = paired(list(d.values()), design.MARGIN[q])
        rec["files"] = d
        out["differences"][f"{hi}-{lo}"] = rec
    return out


def cross(js: dict, q: str, arm: str = "grid") -> dict:
    """The jump by whose research (rows) and who answers (columns), over the accepted runs' files, and
    the two differences it splits the families' gap into."""
    table: dict = {}
    for src in design.FAMILIES:
        table[src] = {}
        for fam in design.FAMILIES:
            vs = [js[(f, fam, arm, q)] for f in sources.ACCEPTED if sources.family(f) == src and (f, fam, arm, q) in js]
            table[src][fam] = float(np.mean(vs)) if vs else None
    by_file = {
        f: js[(f, "sol", arm, q)] - js[(f, "opus", arm, q)]
        for f in sources.ACCEPTED
        if (f, "sol", arm, q) in js and (f, "opus", arm, q) in js
    }
    cells = [table[s][m] for s in design.FAMILIES for m in design.FAMILIES]
    research = None
    if all(c is not None for c in cells):
        research = float(np.mean([table["sol"][m] - table["opus"][m] for m in design.FAMILIES]))
    return {
        "arm": arm,
        "jump_by_source_then_answerer": table,
        "research_sol_minus_opus": research,
        "reasoning_sol_minus_opus": paired(list(by_file.values())),
    }


def abstract_rule(pooled: dict) -> dict:
    """Whether a paper's abstract gives the research runs' jumps alone or beside the alone arm's pooled
    jumps from this test.

    The research runs' jumps stand alone only if both primary verdicts read equivalent, after Holm's
    adjustment, and on both primary questions the unadjusted 90% interval of told minus grid falls
    inside the margin. So the abstract never drops the alone arm's number while a registered verdict
    reads unresolved, different or missing. The main analysis decides; the strict one sits beside it."""
    checks = {}
    for q in design.PRIMARY:
        diffs = (pooled.get(q) or {}).get("differences", {})
        checks[f"{q}:alone-grid"] = diffs.get("alone-grid", {}).get("verdict") == "equivalent"
        checks[f"{q}:told-grid"] = bool(diffs.get("told-grid", {}).get("equivalent"))
    return {"checks": checks, "grid_alone_suffices": all(checks.values()), "gives_both_numbers": not all(checks.values())}


def analyze(rows: list[dict], reference: dict) -> dict:
    js = jumps(rows)
    sj = signed_jumps(js)
    br = bridge(js, reference)
    result: dict = {
        "note": "Model forecasts under stated scenarios, not observations. Jumps and differences are in "
        "points; signed jumps point the registered way when positive.",
        "contexts": len({r["context"] for r in rows}),
        "bridge": br,
        "pooled": {},
        "by_family": {m: {} for m in design.FAMILIES},
        "by_source": {s: {} for s in design.FAMILIES},
        "cross": {},
    }
    for q in QUESTIONS:
        # A primary question pools the models whose bridge holds. Talarico's share takes no verdict, and a
        # 0.1-point bridge can fail on noise alone, so it pools both models and reports its bridge beside them.
        counted = [m for m in design.FAMILIES if br[m][q]["holds"]] if q in design.PRIMARY else list(design.FAMILIES)
        result["pooled"][q] = contrasts(sj, q, counted) if counted else {"families": [], "arms": {}, "differences": {}}
        for m in design.FAMILIES:
            result["by_family"][m][q] = contrasts(sj, q, [m])
        for s in design.FAMILIES:
            sub = {k: v for k, v in sj.items() if sources.family(k[0]) == s}
            result["by_source"][s][q] = contrasts(sub, q, list(design.FAMILIES))
        result["cross"][q] = cross(js, q)
    name = "-".join(PRIMARY_CONTRAST)
    # Holm's family is the two primary tests, always: a question with no pooled result enters it with
    # p = 1, so the other question's test pays for both, as registered.
    recs = [result["pooled"][q].get("differences", {}).get(name, {}) for q in design.PRIMARY]
    tested = ["p_zero" in r and "p_equivalent" in r for r in recs]
    pz_holm = holm([r["p_zero"] if t else 1.0 for r, t in zip(recs, tested)])
    pe_holm = holm([r["p_equivalent"] if t else 1.0 for r, t in zip(recs, tested)])
    for r, t, pz, pe in zip(recs, tested, pz_holm, pe_holm):
        if not t:
            r["verdict"] = "no pooled result"
            continue
        r["p_zero_holm"], r["p_equivalent_holm"] = pz, pe
        # Equivalence comes first: a difference can be nonzero and still smaller than the margin.
        r["verdict"] = "equivalent" if pe < ALPHA else "different" if pz < ALPHA else "unresolved"
    result["abstract"] = abstract_rule(result["pooled"])
    return result


# ----------------------------------------------------------------------------------- replicate rule


def first_batch_spread(rows: list[dict]) -> dict:
    """From the first batch's answers: for each question and family, the pooled variance of answers
    within a cell of the isolated arms, and the pooled variance of the grid contexts' jumps."""
    cells = cell_values(rows)
    grid_jumps: dict = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        if r["arm"] == "grid":
            grid_jumps[(r["file"], r["family"], r["question"])][r["context"]][r["key"]] = r["value"]
    out: dict = {}
    for q in QUESTIONS:
        out[q] = {"cell": {}, "grid": {}}
        for m in design.FAMILIES:
            within = [
                float(np.var(v, ddof=1))
                for (f, fam, arm, qq), by_key in cells.items()
                if fam == m and qq == q and arm != "grid"
                for v in by_key.values()
                if len(v) >= 2
            ]
            grid = []
            for (f, fam, qq), contexts in grid_jumps.items():
                if fam == m and qq == q:
                    js = [jump([c[k] for k in KEYS]) for c in contexts.values() if all(k in c for k in KEYS)]
                    if len(js) >= 2:
                        grid.append(float(np.var(js, ddof=1)))
            if not within or not grid:
                raise ValueError(f"the first batch has too few answers for {q}, {m}")
            out[q]["cell"][m], out[q]["grid"][m] = float(np.mean(within)), float(np.mean(grid))
    return out


def rule_now() -> tuple[int, dict | None, str | None]:
    """The replicate rule on wave 1's answers as `outputs/answers.csv` holds them: the number it picks,
    the spreads it measured, and why it fell back to the most replicates (None when it did not). With
    too few answers to measure a spread, the rule picks the most, as it does when no number meets the
    target."""
    rows = load(wave=1, max_replicate=design.R_BASE)
    try:
        spread = first_batch_spread(rows)
    except ValueError as exc:
        return design.R_MAX, None, str(exc)
    return design.replicates_rule(spread), spread, None


def replicates_due() -> bool:
    """Whether the rule should run now: wave 1 has run and has no context due, live or in review, and
    no result exists yet. `cutoff tick` applies the rule at that point, so no person chooses when."""
    if (paths.DESIGN / "replicates.json").exists():
        return False
    metas = [store.read_meta(r["context"]) for r in store.design_rows() if r["wave"] == 1]
    if not any(m["attempts"] for m in metas):
        return False
    return not any(store.summary(m)["status"] in ("due", "live", "review") for m in metas)


def write_replicates() -> int:
    """Apply the registered rule once the first batch has finished, and record the result."""
    target = paths.DESIGN / "replicates.json"
    if target.exists():
        print("design/replicates.json exists already:", json.loads(target.read_text())["replicates"])
        return 1
    wave1 = [r for r in store.design_rows() if r["wave"] == 1]
    status = [store.summary(store.read_meta(r["context"]))["status"] for r in wave1]
    # The rule waits for the blinded readings too: an answer in review would otherwise be missing from
    # the spreads.
    open_ = sum(s in ("due", "live", "review") for s in status)
    if open_:
        print(f"the first batch has not finished: {open_} of {len(wave1)} contexts still running or awaiting a reading")
        return 1
    r, spread, fallback = rule_now()
    record = {
        "replicates": r,
        "decided_at": store.now(),
        "first_batch_contexts_passed": status.count("passed"),
        "first_batch_contexts": len(wave1),
        "fallback": fallback,
        "spread": spread,
        "required_se": {q: design.required_se(q) for q in design.PRIMARY},
        "projected_se": None if spread is None else {
            q: {str(k): design.projected_se(spread[q]["cell"], spread[q]["grid"], k) for k in range(design.R_BASE, design.R_MAX + 1)}
            for q in design.PRIMARY
        },
    }
    record["registration"] = registration.changes()
    target.write_text(json.dumps(record, indent=1) + "\n")
    print("\n".join(registration.describe(record["registration"])))
    print(f"replicates per cell: {r} (design/replicates.json)")
    return 0


# ------------------------------------------------------------------------------------------- report


def _pm(x, digits=1) -> str:
    return "n/a" if x is None else f"{x:+.{digits}f}"


def _ci(rec, key="ci95", digits=1) -> str:
    return "" if key not in rec else f" [{rec[key][0]:+.{digits}f}, {rec[key][1]:+.{digits}f}]"


def _standing_lines(result: dict) -> list[str]:
    """Where the design stands and which number of contexts a share the analysis used. The registered
    analysis runs once, when no context stays open; any earlier run says INTERIM at its top."""
    d, rr = result.get("design"), result.get("replicate_rule")
    if d is None or rr is None:
        return []
    lines = []
    if d["open"]:
        lines += [f"**INTERIM.** {d['open']} contexts remain open ({d['due']} due, {d['live']} running, {d['review']} "
                  "awaiting the reading). The registered analysis runs once, when none remains; nothing below is "
                  "a registered result.", ""]  # fmt: skip
    lines.append(f"The design at {rr['used']} contexts a share: {d['passed']} passed, {d['stopped']} stopped, "
                 f"{d['open']} open.")  # fmt: skip
    if rr["recorded"] is None:
        rule = ("The replicate rule has not run: wave 1 has not finished." if not rr["wave_1_finished"] else
                f"**The replicate rule has no record, though wave 1 has finished; on its answers the rule gives {rr['rule_now']}.**")
    elif rr["agree"]:
        rule = f"The replicate rule picked {rr['recorded']} on {rr['decided_at']}, and wave 1's answers still give {rr['rule_now']}."
    else:
        rule = (f"**The replicate rule's record says {rr['recorded']} (decided {rr['decided_at']}), but wave 1's "
                f"answers give {rr['rule_now']}.**")  # fmt: skip
    return lines + [rule, ""]


def report(result: dict, strict: dict | None = None, reg: dict | None = None) -> str:
    lines = [
        "# The three arms on Texas: results",
        "",
        "Model forecasts under stated scenarios, not observations. Signed jumps, in points: positive points "
        "the registered way (ERCOT's pause less likely lifted under Hinojosa; a special session more likely). "
        "Brackets hold 95% intervals over evidence files unless a line says 90%.",
        "",
        *(registration.describe(reg) + [""] if reg is not None else []),
        *_standing_lines(result),
        f"Contexts counted: {result['contexts']}.",
        "",
        "## Bridge: closed grid jump minus sealed jump (raw points)",
        "",
        "| Family | Question | Runs | Mean difference | 90% interval | Margin | Holds |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in design.FAMILIES:
        for q in QUESTIONS:
            b = result["bridge"][m][q]
            d = 2 if q == "senate_dem_share" else 1
            lines.append(
                f"| {m} | `{q}` | {b['n']} | {_pm(b.get('mean'), d)} | {_ci(b, 'ci90', d).strip()} | {design.MARGIN[q]:g} | "
                f"{'yes' if b['holds'] else 'no'} |"
            )
    lines += ["", "## The three arms (families pooled where the bridge holds)", "",
              "| Question | Families | Grid | Alone | Told | Alone − grid (90%) | Told − grid (90%) | Told − alone (90%) |",
              "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for q in QUESTIONS:
        p = result["pooled"][q]
        d = 2 if q == "senate_dem_share" else 1
        if not p["families"]:
            lines.append(f"| `{q}` | none: no bridge holds | | | | | | |")
            continue
        arms = " | ".join(f"{_pm(p['arms'][a].get('mean'), d)}{_ci(p['arms'][a], 'ci95', d)}" for a in ARMS)
        diffs = " | ".join(
            f"{_pm(p['differences'][n].get('mean'), d)}{_ci(p['differences'][n], 'ci90', d)}"
            for n in ("alone-grid", "told-grid", "told-alone")
        )
        lines.append(f"| `{q}` | {', '.join(p['families'])} | {arms} | {diffs} |")
    lines += ["", "## Primary tests: alone minus grid", "",
              "| Question | Difference | 90% interval | Margin | Equivalence p (Holm) | Zero p (Holm) | Verdict |",
              "|---|---|---|---|---|---|---|"]  # fmt: skip
    for q in design.PRIMARY:
        r = result["pooled"][q].get("differences", {}).get("alone-grid", {})
        if "p_zero_holm" not in r:
            lines.append(f"| `{q}` | no pooled result | | | | | |")
            continue
        lines.append(
            f"| `{q}` | {_pm(r['mean'])} | {_ci(r, 'ci90').strip()} | {r['margin']:g} | {r['p_equivalent']:.3f} "
            f"({r['p_equivalent_holm']:.3f}) | {r['p_zero']:.3f} ({r['p_zero_holm']:.3f}) | {r['verdict']} |"
        )
    a = result["abstract"]
    lines += ["", "## What the abstract reports", "",
              ("The research runs' jumps alone: both primary verdicts read equivalent, and both told-minus-grid 90% "
               "intervals fall inside the margin."
               if a["grid_alone_suffices"] else
               "The research runs' jumps beside the alone arm's pooled jumps: "
               + ", ".join(k for k, ok in a["checks"].items() if not ok) + " did not show equivalence."),
              "", "## Each family alone", "",
              "| Family | Question | Grid | Alone | Told | Alone − grid (90%) | Told − grid (90%) |", "|---|---|---|---|---|---|---|"]  # fmt: skip
    for m in design.FAMILIES:
        for q in QUESTIONS:
            p = result["by_family"][m][q]
            d = 2 if q == "senate_dem_share" else 1
            arms = " | ".join(f"{_pm(p['arms'][a].get('mean'), d)}{_ci(p['arms'][a], 'ci95', d)}" for a in ARMS)
            diffs = " | ".join(
                f"{_pm(p['differences'][n].get('mean'), d)}{_ci(p['differences'][n], 'ci90', d)}" for n in ("alone-grid", "told-grid")
            )
            lines.append(f"| {m} | `{q}` | {arms} | {diffs} |")
    lines += ["", "## Whose research, who answers (grid arm, accepted runs' files, raw jumps)", "",
              "| Question | Opus files, Opus answers | Opus files, Sol answers | Sol files, Opus answers | Sol files, Sol answers | Research: Sol − Opus files | Reasoning: Sol − Opus answers |",
              "|---|---|---|---|---|---|---|"]  # fmt: skip
    for q in QUESTIONS:
        c = result["cross"][q]
        t = c["jump_by_source_then_answerer"]
        d = 2 if q == "senate_dem_share" else 1
        rs = c["reasoning_sol_minus_opus"]
        lines.append(
            f"| `{q}` | {_pm(t['opus']['opus'], d)} | {_pm(t['opus']['sol'], d)} | {_pm(t['sol']['opus'], d)} | {_pm(t['sol']['sol'], d)} | "
            f"{_pm(c['research_sol_minus_opus'], d)} | {_pm(rs.get('mean'), d)}{_ci(rs, 'ci95', d)} |"
        )
    if strict is not None:
        lines += ["", "## Without repaired answers or answers whose prior context needed a reading", "",
                  f"Contexts counted: {strict['contexts']}.", "",
                  "| Question | Alone − grid | 90% interval | Verdict |", "|---|---|---|---|"]  # fmt: skip
        for q in design.PRIMARY:
            r = strict["pooled"][q].get("differences", {}).get("alone-grid", {})
            lines.append(f"| `{q}` | {_pm(r.get('mean'))} | {_ci(r, 'ci90').strip()} | {r.get('verdict', 'n/a')} |")
    return "\n".join(lines) + "\n"


def replicates_used() -> int:
    p = paths.DESIGN / "replicates.json"
    return int(json.loads(p.read_text())["replicates"]) if p.exists() else design.R_BASE


def design_counts(r: int) -> dict:
    """Where every context of the design stands, up to `r` contexts a share, from the public tables
    (`design/contexts.csv` and `outputs/attempts.csv`), so a reader without the private store gets the
    same counts. `open` counts the contexts still due, live or awaiting the reading."""
    attempts: dict = defaultdict(list)
    path = paths.OUTPUTS / "attempts.csv"
    if path.exists():
        with path.open() as f:
            for row in csv.DictReader(f):
                attempts[row["context"]].append({"state": row["state"]})
    counts = dict.fromkeys(("passed", "stopped", "due", "live", "review"), 0)
    for row in store.design_rows():
        if row["replicate"] <= r:
            counts[store.summary({"context": row["context"], "attempts": attempts.get(row["context"], [])})["status"]] += 1
    counts["open"] = counts["due"] + counts["live"] + counts["review"]
    return counts


def replicate_record(r: int) -> dict:
    """The number of contexts a share this analysis uses, beside what the rule's record says and what
    the rule gives on wave 1's answers now. They agree unless someone skipped the rule or edited its
    record."""
    p = paths.DESIGN / "replicates.json"
    recorded = json.loads(p.read_text()) if p.exists() else None
    wave1 = [row for row in store.design_rows() if row["wave"] == 1 and row["replicate"] <= design.R_BASE]
    attempts: dict = defaultdict(list)
    path = paths.OUTPUTS / "attempts.csv"
    if path.exists():
        with path.open() as f:
            for row in csv.DictReader(f):
                attempts[row["context"]].append({"state": row["state"]})
    states = [store.summary({"context": row["context"], "attempts": attempts.get(row["context"], [])})["status"] for row in wave1]
    ran = any(attempts.get(row["context"]) for row in wave1)
    finished = ran and not any(s in ("due", "live", "review") for s in states)
    now = rule_now()[0] if finished else None
    return {
        "used": r,
        "recorded": recorded["replicates"] if recorded else None,
        "decided_at": recorded.get("decided_at") if recorded else None,
        "wave_1_finished": finished,
        "rule_now": now,
        "agree": (recorded is not None and recorded["replicates"] == now) if finished else recorded is None,
    }


def main() -> int:
    reference = json.loads((paths.DESIGN / "reference.json").read_text())
    r = replicates_used()
    result = analyze(load(max_replicate=r), reference)
    strict = analyze(load(max_replicate=r, strict=True), reference)
    result["replicates"] = r
    result["design"] = design_counts(r)
    result["complete"] = result["design"]["open"] == 0
    result["replicate_rule"] = replicate_record(r)
    reg = registration.changes()
    paths.OUTPUTS.mkdir(exist_ok=True)
    (paths.OUTPUTS / "results.json").write_text(json.dumps({"registration": reg, "main": result, "strict": strict}, indent=1) + "\n")
    text = report(result, strict, reg)
    (paths.OUTPUTS / "results.md").write_text(text)
    print(text)
    return 0
