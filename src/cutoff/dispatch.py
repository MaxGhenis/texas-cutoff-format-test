"""Send contexts to Subfleet's isolated lanes, a few at a time, in the registered order.

Each context is one `subfleet run` in isolated mode: a pinned model, a read-only session in the empty
sandbox folder, and the registered prompt on standard input. The job's request id is a UUID5 of the
context's id and attempt number, so sending the same attempt twice creates one job.

`dispatch` refuses to send anything unless the registration stands (`registration.problems`): the
stamped list exists, the briefs and the four design tables that name the stimulus
(`registration.STIMULUS`) still match it, and each prompt file on disk has the hash
`design/prompts.csv` gives it. It also refuses while the sandbox folder holds anything besides the two
notes with their built text (`sandbox_problems`).

Dry run: a family sends nothing until its dry run has passed (`dryrun.py`).

Pilot: until a family's first context passes, it runs one context at a time, and two failed answers
or three runs with no answer, with none passed, hold it until a person sends the next by hand (`pilot`).
It also waits while its first answer awaits the blinded reading.

Waves: wave 1 (the first batch) goes first. A family's wave 2 starts when its wave 1 has finished.
Wave 3 (replicates 4 to 6) starts only after `design/replicates.json` exists, and only up to the
number of replicates it records.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import uuid

from . import design, dryrun, paths, registration, store

MAX_IN_FLIGHT = int(os.environ.get("CUTOFF_MAX_IN_FLIGHT", "4"))  # per family
PILOT_FAILURES = 2
PILOT_LOST = 3


def pilot(rows: list[dict], metas: dict, fam: str) -> tuple[int, str | None, bool]:
    """How many of a family's contexts may run at once, why none may, and whether `--pilot` lifts that.

    Until a family's first context passes, it runs one context at a time, so a fault in the closed
    setup (say, a lane that reads the folder's note and writes the code word) costs one attempt, not
    a wave. After two failed answers, or three runs that ended with no answer, with none passed, it
    stops until a person reads them and sends the next one by hand with `cutoff dispatch --pilot`.
    A withdrawn job never ran and counts toward neither. While an answer awaits the blinded reading
    and none has passed, the family also waits, so a fault that shows only in `prior_context` costs
    one context. The reading releases that wait; `--pilot` does not."""
    states = [a["state"] for r in rows if r["family"] == fam for a in metas[r["context"]]["attempts"]]
    if "passed" in states:
        return MAX_IN_FLIGHT, None, False
    if "review" in states:
        return 0, f"{fam}: its first answer awaits the blinded reading (cutoff flags), and none has passed", False
    failed, lost = states.count("failed"), states.count("lost")
    if failed >= PILOT_FAILURES or lost >= PILOT_LOST:
        return 0, (f"{fam}: {failed} failed answers and {lost} runs with no answer, and none passed; read them "
                   "(cutoff status, the attempt folders) and send the next one by hand with "
                   f"`cutoff dispatch --family {fam} --limit 1 --pilot`"), True
    return 1, None, False


def registration_problems() -> list[str]:
    return registration.problems()


def prompt_hashes() -> dict[str, str]:
    with (paths.DESIGN / "prompts.csv").open() as f:
        return {r["prompt"]: r["sha256"] for r in csv.DictReader(f)}


def request_id(cid: str, attempt: int) -> str:
    """Attempt 1 uses the id in design/contexts.csv; a later attempt gets its own."""
    return str(uuid.uuid5(design.NAMESPACE, cid if attempt == 1 else f"{cid}#a{attempt}"))


def command(row: dict, attempt: int) -> list[str]:
    prompt = paths.PRIVATE / "prompts" / f"{row['prompt']}.md"
    name = row["name"] if attempt == 1 else f"{row['name']}-a{attempt}"
    return [
        "subfleet", "run", "-m", design.PIN[row["family"]], "-I", "-s", "read-only",
        "-D", str(paths.SANDBOX), "-C", str(paths.SANDBOX), "--no-needs-shell", "-d",
        "-p", str(prompt), "-n", name, "--request-id", request_id(row["context"], attempt), "--json",
    ]  # fmt: skip


def replicates_allowed() -> int:
    p = paths.DESIGN / "replicates.json"
    return int(json.loads(p.read_text())["replicates"]) if p.exists() else design.R_BASE


def eligible(rows: list[dict], metas: dict[str, dict]) -> list[dict]:
    """The contexts that may run now, in order: wave 1; a family's wave 2 once its wave 1 has no
    context left due or live (one awaiting the blinded reading does not hold it back); wave 3 up to the
    recorded number of replicates."""
    status = {cid: store.summary(m)["status"] for cid, m in metas.items()}
    r_max = replicates_allowed()
    wave1_open = {
        fam: any(status[r["context"]] in ("due", "live") for r in rows if r["wave"] == 1 and r["family"] == fam)
        for fam in design.FAMILIES
    }
    out = []
    for r in rows:
        if status[r["context"]] != "due" or r["replicate"] > r_max:
            continue
        if r["wave"] >= 2 and wave1_open[r["family"]]:
            continue
        out.append(r)
    return out


def sandbox_problems() -> list[str]:
    from . import build

    if not paths.SANDBOX.is_dir():
        return [f"the sandbox {paths.SANDBOX} is missing; run `cutoff build`"]
    names = sorted(p.name for p in paths.SANDBOX.iterdir())
    if names != sorted(build.CANARY_FILES):
        return [f"the sandbox holds {names}, not just the canary files"]
    if any((paths.SANDBOX / n).read_text() != build.CANARY_TEXT for n in build.CANARY_FILES):
        return ["a canary file in the sandbox changed"]
    return []


def main(wave: int | None = None, family: str | None = None, limit: int | None = None, dry_run: bool = False,
         pilot_ok: bool = False) -> int:
    with store.lock():
        problems = registration_problems() + sandbox_problems()
        if problems and not dry_run:
            for p in problems:
                print("refusing to dispatch:", p)
            return 1
        rows = store.design_rows()
        metas = {r["context"]: store.read_meta(r["context"]) for r in rows}
        todo = eligible(rows, metas)
        hashes = prompt_hashes()
        bad = sorted(
            {r["prompt"] for r in todo}
            - {pid for pid in {r["prompt"] for r in todo}
               if (paths.PRIVATE / "prompts" / f"{pid}.md").is_file()
               and registration.sha(paths.PRIVATE / "prompts" / f"{pid}.md") == hashes.get(pid)}
        )  # fmt: skip
        if bad:
            for pid in bad:
                print(f"refusing to dispatch: the prompt file {pid}.md does not match design/prompts.csv")
            return 1
        sent = 0
        for fam in design.FAMILIES:
            if family and fam != family:
                continue
            live = sum(
                store.summary(metas[r["context"]])["status"] == "live" for r in rows if r["family"] == fam
            )
            if not dryrun.passed(fam):
                print(f"holding {fam}: its dry run has not passed (cutoff dryrun)")
                continue
            cap, why, by_hand = pilot(rows, metas, fam)
            lift = pilot_ok and (by_hand or not why)
            if why and not lift:
                print("holding", why)
            room = (max(cap, 1) if lift else cap) - live
            for r in todo:
                if room <= 0 or (limit is not None and sent >= limit):
                    break
                if r["family"] != fam or (wave is not None and r["wave"] != wave):
                    continue
                meta = metas[r["context"]]
                attempt = len(meta["attempts"]) + 1
                cmd = command(r, attempt)
                if dry_run:
                    print("would send", r["name"], r["context"], f"(attempt {attempt})")
                else:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    job_id = None
                    for line in proc.stdout.splitlines():
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(obj, dict):
                            continue
                        job = obj.get("job") if isinstance(obj.get("job"), dict) else {}
                        job_id = obj.get("job_id") or job.get("job_id")
                        if job_id:
                            break
                    if proc.returncode != 0 or not job_id:
                        print(f"subfleet refused {r['context']} (rc {proc.returncode}): {proc.stderr[-400:]}")
                        break  # the lanes are closed or Subfleet is busy: try again next tick
                    meta["attempts"].append(
                        {
                            "attempt": attempt,
                            "request_id": request_id(r["context"], attempt),
                            "job_id": job_id,
                            "command": cmd,
                            "dispatched_at": store.now(),
                            "state": "submitted",
                        }
                    )
                    store.write_meta(meta)
                    print("sent", r["name"], r["context"], job_id)
                room -= 1
                sent += 1
        print(f"{'would send' if dry_run else 'sent'} {sent}; {len(todo)} were due")
    return 0
