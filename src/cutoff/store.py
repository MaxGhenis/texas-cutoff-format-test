"""The run's private bookkeeping: one folder per context under PRIVATE/contexts/, with `meta.json`
(its attempts and their states) and one folder per attempt (`a1`, `a2`, ...) holding what Subfleet
kept and what the audit and the answer check made of it.

An attempt's `state` is `submitted` until its Subfleet job ends, then one of:
- `review`: everything passed, but its `prior_context` awaits the blinded reading (`collect.py`);
- `passed`: the audit and the answer check passed; its numbers enter `outputs/answers.csv`;
- `failed`: the run produced an answer that failed the audit or the answer check; a fresh context
  replaces it, at most twice (`MAX_ATTEMPTS` answers per context);
- `lost`: the run ended with no answer (a lane failure); it counts as no attempt, and the context runs
  again, up to `MAX_LOST` times;
- `withdrawn`: the job ended before any lane started it (Subfleet cancelled or expired it in the
  queue); it never ran, counts toward neither limit, and the context goes back in line.
"""

from __future__ import annotations

import csv
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import paths

MAX_ATTEMPTS = 3  # answers per context: the first and at most two replacements
MAX_LOST = 5  # runs that end with no answer, before the context stops


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def contexts_dir() -> Path:
    return paths.PRIVATE / "contexts"


@contextmanager
def lock():
    """One tick at a time: dispatch and collect both hold this while they work."""
    paths.PRIVATE.mkdir(parents=True, exist_ok=True)
    with open(paths.PRIVATE / "tick.lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another cutoff tick holds the lock") from None
        yield


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_meta(cid: str) -> dict:
    p = contexts_dir() / cid / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {"context": cid, "attempts": []}


def write_meta(meta: dict) -> None:
    write_atomic(contexts_dir() / meta["context"] / "meta.json", json.dumps(meta, indent=1) + "\n")


def design_rows() -> list[dict]:
    """The registered contexts, in dispatch order, from the committed design/contexts.csv."""
    with (paths.DESIGN / "contexts.csv").open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["replicate"], r["wave"], r["order"] = int(r["replicate"]), int(r["wave"]), int(r["order"])
    return sorted(rows, key=lambda r: r["order"])


def summary(meta: dict) -> dict:
    """Where a context stands: `passed` (an attempt passed), `live` (an attempt awaits its job),
    `review` (an answer awaits the blinded reading; it holds no lane), `stopped` (out of attempts), or
    `due` (it needs a run); with its counts."""
    attempts = meta["attempts"]
    states = [a["state"] for a in attempts]
    answered = sum(s in ("passed", "failed") for s in states)
    lost = states.count("lost")
    if "passed" in states:
        status = "passed"
    elif "submitted" in states:
        status = "live"
    elif "review" in states:
        status = "review"
    elif answered >= MAX_ATTEMPTS or lost >= MAX_LOST:
        status = "stopped"
    else:
        status = "due"
    return {"status": status, "answered": answered, "lost": lost, "attempts": len(attempts)}
