"""Collect finished contexts: copy what Subfleet kept, audit it, check the answer, and write the
public tables.

For each attempt whose Subfleet job has ended, `collect` copies the launch record, the event stream,
the finalization record and the prompt as sent into PRIVATE/contexts/<context>/a<N>/, runs the audit
(`audit.py`) and the answer check (`response.py`), and sets the attempt's state (`store.py`).

An answer whose `prior_context` says more than a bare "none", "nothing" or "n/a" waits in state
`review` for the blinded reading: `cutoff flags` prints each distinct text with its key and nothing
else, the reader files a decision in `review/prior_context.csv` (`cutoff flags --clean KEY` or
`--contaminated KEY`), and the next `collect` passes or fails the attempt. Each model's dry run
(`dryrun.py`) puts its own `prior_context` text, if any, through the same reading. A decision, once
filed, stands: `decide` refuses to change it. The public file holds each key, decision and reason;
the texts, which can quote the evidence, go to PRIVATE/review/prior_context_texts.csv.

`outputs/answers.csv` holds every passed context's numbers, one row per question and cell, and
`outputs/attempts.csv` every attempt's state. Both are rebuilt in full from the private store, so
they never depend on the order of collection.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

from . import audit, build, paths, store
from .jump import QUANTITY, QUESTIONS, answer_value
from .response import QUANTILE_KEYS, ResponseError, keys_for, read_answer

FINISHED = {"succeeded", "failed", "cancelled", "canceled", "lost", "killed", "expired", "abandoned"}
KEPT = ("launch.json", "finalization.json", "exit.json", "prompt.sent.md")
PRIOR_REVIEW = paths.ROOT / "review" / "prior_context.csv"
ANSWER_COLUMNS = [
    "context", "file", "source_family", "family", "arm", "cell", "replicate", "wave", "attempt", "question",
    "key", "value", *QUANTILE_KEYS, "repaired", "prior_read", "canary", "job_id",
]  # fmt: skip
ATTEMPT_COLUMNS = [
    "context", "attempt", "job_id", "state", "problems", "tool_calls", "model_served", "attested",
    "lead_sha256", "repairs", "prior_key", "canary", "dispatched_at", "finished_at",
]  # fmt: skip


def show(job_id: str) -> dict | None:
    try:
        proc = subprocess.run(["subfleet", "runs", "show", job_id, "--json"], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    try:
        info = json.loads(proc.stdout)
    except ValueError:
        return None
    return info if isinstance(info, dict) else None


def prior_decisions() -> dict[str, str]:
    if not PRIOR_REVIEW.exists():
        return {}
    with PRIOR_REVIEW.open() as f:
        return {r["key"]: r["decision"] for r in csv.DictReader(f)}


def judge(row: dict, folder: Path) -> dict:
    """Audit one collected attempt's files and check its answer. Returns the attempt's record:
    state `passed`, `failed` or `review`, with the problems found."""
    stream_path = folder / "stream.jsonl"
    stream = stream_path.read_text() if stream_path.exists() else ""
    launch = json.loads((folder / "launch.json").read_text()) if (folder / "launch.json").exists() else {}
    fin_path = folder / "finalization.json"
    finalization = json.loads(fin_path.read_text()) if fin_path.exists() else None
    check = (audit.claude if row["family"] == "opus" else audit.codex)(stream, launch, finalization, paths.SANDBOX)
    problems = list(check["problems"])
    registered = (paths.PRIVATE / "prompts" / f"{row['prompt']}.md").read_text()
    sent_path = folder / "prompt.sent.md"
    sent = audit.sent_prompt(sent_path.read_text() if sent_path.exists() else "", registered)
    if not sent["ok"]:
        problems.append("the prompt as sent differs from the registered prompt")
    final = check["final"]
    (folder / "final.md").write_text(final)
    if audit.has_canary(final, build.CANARY_WORD):
        problems.append("the answer carries the sandbox's canary word: the context read a project file")
    record = {
        "tool_calls": check["tool_calls"],
        "model_served": check["model_served"],
        "attested": check["attested"],
        "lead_sha256": sent["lead_sha256"],
        "canary": audit.has_canary(final, build.CANARY_WORD),
        "repairs": 0,
        "prior_key": None,
    }
    keys, cell = keys_for(row["arm"], row["cell"])
    answer = None
    try:
        answer, repairs = read_answer(final, keys, cell)
    except ResponseError as exc:
        problems += [f"answer: {p}" for p in exc.problems]
    if answer is not None:
        record["repairs"] = len(repairs)
        prior = str(answer.forecaster.get("prior_context") or "")
        (folder / "answer.json").write_text(
            json.dumps(
                {"values": answer.values, "forecaster": answer.forecaster, "scenario": answer.scenario,
                 "reasoning": answer.reasoning, "repairs": repairs},
                indent=1,
            )
            + "\n"
        )
        if audit.prior_flag(prior):
            record["prior_key"] = audit.prior_key(prior)
    record["problems"] = problems
    if problems:
        record["state"] = "failed"
    elif record["prior_key"]:
        decision = prior_decisions().get(record["prior_key"])
        record["state"] = {"clean": "passed", "contaminated": "failed"}.get(decision, "review")
        if decision == "contaminated":
            record["problems"] = ["prior_context: read as contaminated"]
    else:
        record["state"] = "passed"
    (folder / "audit.json").write_text(json.dumps(record, indent=1) + "\n")
    return record


def collect_attempt(row: dict, meta: dict, att: dict) -> bool:
    """Bring one submitted attempt up to date. Returns whether its state changed."""
    info = show(att["job_id"])
    if info is None:
        return False
    job = info.get("job") or {}
    if job.get("state") not in FINISHED:
        return False
    att["job_state"], att["finished_at"] = job.get("state"), job.get("finished_at")
    done = [a for a in info.get("attempts", []) if a.get("state") == "succeeded"]
    if not done:
        # A job that ended before any lane started it (cancelled or expired in the queue) never ran.
        att["state"] = "lost" if info.get("attempts") else "withdrawn"
        return True
    src = paths.JOBS / done[-1]["attempt_id"]
    folder = store.contexts_dir() / meta["context"] / f"a{att['attempt']}"
    folder.mkdir(parents=True, exist_ok=True)
    for name in KEPT:
        if (src / name).exists():
            shutil.copyfile(src / name, folder / name)
    stream = src / "stream.jsonl" if (src / "stream.jsonl").exists() else src / "stdout"
    if stream.exists():
        shutil.copyfile(stream, folder / "stream.jsonl")
    att["lane_id"] = done[-1].get("lane_id")
    att.update(judge(row, folder))
    return True


def rejudge(row: dict, meta: dict, att: dict) -> bool:
    """An attempt in review moves once the reading has a decision for its text."""
    decision = prior_decisions().get(att.get("prior_key"))
    if decision == "clean":
        att["state"] = "passed"
    elif decision == "contaminated":
        att["state"], att["problems"] = "failed", ["prior_context: read as contaminated"]
    else:
        return False
    return True


def answer_rows(row: dict, att: dict) -> list[dict]:
    folder = store.contexts_dir() / row["context"] / f"a{att['attempt']}"
    data = json.loads((folder / "answer.json").read_text())
    out = []
    for q in QUESTIONS:
        for key, v in data["values"][q].items():
            rec = {c: "" for c in ANSWER_COLUMNS}
            rec.update({k: row[k] for k in ("context", "file", "source_family", "family", "arm", "cell", "replicate", "wave")})
            rec.update(
                attempt=att["attempt"], question=q, key=key, value=repr(answer_value(q, v)),
                repaired=int(bool(att.get("repairs"))), prior_read=int(bool(att.get("prior_key"))),
                canary=int(bool(att.get("canary"))), job_id=att["job_id"],
            )  # fmt: skip
            if q in QUANTITY:
                rec.update(dict(zip(QUANTILE_KEYS, (repr(float(x)) for x in v))))
            out.append(rec)
    return out


def _csv(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_tables() -> tuple[int, int]:
    rows = store.design_rows()
    answers, attempts = [], []
    for r in rows:
        meta = store.read_meta(r["context"])
        for att in meta["attempts"]:
            attempts.append(
                {
                    "context": r["context"], "attempt": att["attempt"], "job_id": att.get("job_id", ""),
                    "state": att["state"], "problems": " | ".join(att.get("problems") or []),
                    "tool_calls": att.get("tool_calls", ""), "model_served": att.get("model_served") or "",
                    "attested": att.get("attested", ""), "lead_sha256": att.get("lead_sha256") or "",
                    "repairs": att.get("repairs", ""), "prior_key": att.get("prior_key") or "",
                    "canary": att.get("canary", ""), "dispatched_at": att.get("dispatched_at", ""),
                    "finished_at": att.get("finished_at") or "",
                }  # fmt: skip
            )
            if att["state"] == "passed":
                answers += answer_rows(r, att)
    paths.OUTPUTS.mkdir(exist_ok=True)
    (paths.OUTPUTS / "answers.csv").write_text(_csv(ANSWER_COLUMNS, answers))
    (paths.OUTPUTS / "attempts.csv").write_text(_csv(ATTEMPT_COLUMNS, attempts))
    return len(answers), len(attempts)


def main() -> int:
    with store.lock():
        rows = store.design_rows()
        changed = 0
        for r in rows:
            meta = store.read_meta(r["context"])
            dirty = False
            for att in meta["attempts"]:
                if att["state"] == "submitted":
                    dirty |= collect_attempt(r, meta, att)
                elif att["state"] == "review":
                    dirty |= rejudge(r, meta, att)
            if dirty:
                store.write_meta(meta)
                changed += 1
        n_answers, n_attempts = write_tables()
        print(f"{changed} contexts changed; {n_attempts} attempts, {n_answers} answer rows in outputs/")
    return 0


def flagged() -> dict[str, dict]:
    """Each distinct `prior_context` text awaiting or past the reading: {key: {text, count, decision}}."""
    decisions = prior_decisions()
    out: dict[str, dict] = {}
    for r in store.design_rows():
        meta = store.read_meta(r["context"])
        for att in meta["attempts"]:
            key = att.get("prior_key")
            if not key:
                continue
            answer = store.contexts_dir() / r["context"] / f"a{att['attempt']}" / "answer.json"
            text = str(json.loads(answer.read_text())["forecaster"].get("prior_context") or "").strip()
            rec = out.setdefault(key, {"text": text, "count": 0, "decision": decisions.get(key, "")})
            rec["count"] += 1
    from . import dryrun

    for key, text in dryrun.flagged_texts().items():  # the dry runs' texts take the same reading
        rec = out.setdefault(key, {"text": text, "count": 0, "decision": decisions.get(key, "")})
        rec["count"] += 1
    return out


def decide(key_prefix: str, decision: str, reason: str) -> int:
    """File a reading decision for the one flagged text whose key starts with `key_prefix`."""
    matches = [k for k in flagged() if k.startswith(key_prefix)]
    if len(matches) != 1:
        print(f"{len(matches)} flagged texts match {key_prefix!r}")
        return 1
    key = matches[0]
    filed = prior_decisions()
    if key in filed:
        print(f"{key[:12]} already has the decision {filed[key]!r}; a filed decision stands")
        return 1
    rows = []
    if PRIOR_REVIEW.exists():
        with PRIOR_REVIEW.open() as f:
            rows = list(csv.DictReader(f))
    rows.append({"key": key, "decision": decision, "reason": reason, "read_at": store.now()})
    PRIOR_REVIEW.parent.mkdir(exist_ok=True)
    store.write_atomic(PRIOR_REVIEW, _csv(["key", "decision", "reason", "read_at"], rows))
    texts = paths.PRIVATE / "review" / "prior_context_texts.csv"
    trows = []
    if texts.exists():
        with texts.open() as f:
            trows = [r for r in csv.DictReader(f) if r["key"] != key]
    trows.append({"key": key, "text": flagged()[key]["text"]})
    store.write_atomic(texts, _csv(["key", "text"], trows))
    return 0


def status_table() -> str:
    rows = store.design_rows()
    tally: dict[tuple, dict] = {}
    for r in rows:
        s = store.summary(store.read_meta(r["context"]))
        cell = tally.setdefault((r["wave"], r["family"], r["arm"]), {})
        cell[s["status"]] = cell.get(s["status"], 0) + 1
    lines = ["wave family arm    passed live review due stopped"]
    for (wave, fam, arm), c in sorted(tally.items()):
        lines.append(
            f"{wave:<4} {fam:<6} {arm:<6} {c.get('passed', 0):>6} {c.get('live', 0):>4} {c.get('review', 0):>6} "
            f"{c.get('due', 0):>3} {c.get('stopped', 0):>7}"
        )
    return "\n".join(lines)
