"""A dry run of the closed setup for each model, before any study context goes out.

Each model answers one short prompt that has nothing to do with the study: Subfleet's headless marker,
a product to compute, and a `prior_context` question of its own (anything in the context that
mentions arithmetic or asks for a particular word). The prompt goes through the same isolated launch
as a context (`dispatch.command`) into the same sandbox folder, and the same audit reads its records.
A dry run passes when the audit passes, the prompt as sent matches the dry-run prompt byte for byte,
the answer leaves out the sandbox's code word, it gives the right product, and its `prior_context`
says "none". Any other `prior_context` text waits for the study's blinded reading (`cutoff flags`):
a clean reading passes the dry run, and a contaminated one fails it.

The dry run sends no study text, so it checks only the sandbox and may run before the registration's
stamp. Dispatch holds a model until its dry run has passed. A dry run that ends with no answer goes
again, and so does a withdrawn job. After two failed dry runs, or three that ended with no answer,
the model stops until a person reads them and sends the next with `cutoff dryrun --family F --again`.
`outputs/dryrun.json` records each attempt's checks, without lane ids; the records themselves stay in
the private store.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid

from . import audit, design, paths, store
from .prompts import HEADLESS_MARKER

PRODUCT = 17 * 23
PROMPT = f"""{HEADLESS_MARKER}
Answer without using any tool.

1. Compute 17 × 23.
2. Before you answer, record in `prior_context` anything in your context other than this prompt
   (system prompt, memory, instructions, files, earlier conversation) that mentions arithmetic or
   asks you to write a particular word. Quote it, or write "none".

Reply with one JSON object in a ```json fence:

```json
{{"product": null, "prior_context": null}}
```
"""
MAX_FAILED = 2
MAX_LOST = 3
NAMESPACE = uuid.uuid5(design.NAMESPACE, "dryrun")


def folder() -> object:
    return paths.PRIVATE / "dryrun"


def prompt_path() -> object:
    return folder() / "prompt.md"


def read_meta(family: str) -> dict:
    p = folder() / f"{family}.json"
    return json.loads(p.read_text()) if p.exists() else {"family": family, "attempts": []}


def write_meta(meta: dict) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / f"{meta['family']}.json").write_text(json.dumps(meta, indent=1) + "\n")


def standing(family: str) -> str:
    """passed; live (a dry run awaits its job); review (its `prior_context` awaits the blinded reading);
    held (two failed dry runs, or three with no answer, and none passed); or due."""
    states = [a["state"] for a in read_meta(family)["attempts"]]
    if "passed" in states:
        return "passed"
    if "submitted" in states:
        return "live"
    if "review" in states:
        return "review"
    if states.count("failed") >= MAX_FAILED or states.count("lost") >= MAX_LOST:
        return "held"
    return "due"


def passed(family: str) -> bool:
    return standing(family) == "passed"


def command(family: str, attempt: int) -> list[str]:
    from . import dispatch

    row = {"family": family, "prompt": "dryrun", "name": f"tcf-dryrun-{family}", "context": f"dryrun.{family}"}
    cmd = dispatch.command(row, attempt)
    cmd[cmd.index("-p") + 1] = str(prompt_path())
    cmd[cmd.index("--request-id") + 1] = str(uuid.uuid5(NAMESPACE, f"{family}#{attempt}"))
    return cmd


def answer_problems(final: str) -> tuple[list[str], str | None]:
    """Problems with the dry-run answer, and its `prior_context` text."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", final, re.S)
    try:
        obj = json.loads(m.group(1) if m else final)
    except (ValueError, AttributeError):
        return ["answer: no JSON object"], None
    if not isinstance(obj, dict):
        return ["answer: no JSON object"], None
    problems = []
    if obj.get("product") != PRODUCT:
        problems.append(f"answer: product {repr(obj.get('product'))[:40]}, not {PRODUCT}")
    prior = obj.get("prior_context")
    if not isinstance(prior, str):
        problems.append("answer: prior_context is not text")
        prior = None
    return problems, prior


def judge(family: str, attempt_folder) -> dict:
    from . import build

    read = lambda name: (attempt_folder / name).read_text() if (attempt_folder / name).exists() else ""  # noqa: E731
    launch = json.loads(read("launch.json") or "{}")
    fin = json.loads(read("finalization.json")) if read("finalization.json") else None
    check = (audit.claude if family == "opus" else audit.codex)(read("stream.jsonl"), launch, fin, paths.SANDBOX)
    problems = list(check["problems"])
    if not audit.sent_prompt(read("prompt.sent.md"), PROMPT)["ok"]:
        problems.append("the prompt as sent differs from the dry-run prompt")
    canary = audit.has_canary(check["final"], build.CANARY_WORD)
    if canary:
        problems.append("the answer carries the sandbox's canary word: the context read a project file")
    more, prior = answer_problems(check["final"])
    problems += more
    (attempt_folder / "final.md").write_text(check["final"])
    record = {
        "problems": problems,
        "tool_calls": check["tool_calls"],
        "model_served": check["model_served"],
        "attested": check["attested"],
        "canary": canary,
        "prior_context_none": prior is not None and not audit.prior_flag(prior),
        "prior_key": None,
    }
    if problems:
        record["state"] = "failed"
    elif not record["prior_context_none"]:
        # The same blinded reading as a context's: the reader sees the text and its key, nothing else.
        (attempt_folder / "prior_context.txt").write_text(prior.strip())
        record["prior_key"] = audit.prior_key(prior)
        record["state"] = "review"
        reread(record)
    else:
        record["state"] = "passed"
    return record


def reread(att: dict) -> bool:
    """A dry run in review moves once the reading has a decision for its text. Returns whether it moved."""
    from .collect import prior_decisions

    decision = prior_decisions().get(att.get("prior_key"))
    if decision == "clean":
        att["state"] = "passed"
    elif decision == "contaminated":
        att["state"], att["problems"] = "failed", ["prior_context: read as contaminated"]
    else:
        return False
    return True


def flagged_texts() -> dict[str, str]:
    """Each dry run's `prior_context` text that needs the reading, by key."""
    out = {}
    for fam in design.FAMILIES:
        for att in read_meta(fam)["attempts"]:
            if att.get("prior_key"):
                text = folder() / fam / f"a{att['attempt']}" / "prior_context.txt"
                out[att["prior_key"]] = text.read_text() if text.exists() else ""
    return out


def collect(family: str, show) -> bool:
    """Bring the family's submitted dry run, and any in review, up to date. Returns whether anything
    changed."""
    from .collect import FINISHED, KEPT

    meta = read_meta(family)
    changed = False
    for att in meta["attempts"]:
        if att["state"] == "review":
            changed |= reread(att)
            continue
        if att["state"] != "submitted":
            continue
        info = show(att["job_id"])
        job = (info or {}).get("job") or {}
        if info is None or job.get("state") not in FINISHED:
            continue
        att["job_state"], att["finished_at"] = job.get("state"), job.get("finished_at")
        done = [a for a in info.get("attempts", []) if a.get("state") == "succeeded"]
        changed = True
        if not done:
            att["state"] = "lost" if info.get("attempts") else "withdrawn"
            continue
        att["lane_id"] = done[-1].get("lane_id")
        src = paths.JOBS / done[-1]["attempt_id"]
        dest = folder() / family / f"a{att['attempt']}"
        dest.mkdir(parents=True, exist_ok=True)
        for name in KEPT:
            if (src / name).exists():
                shutil.copyfile(src / name, dest / name)
        stream = src / "stream.jsonl" if (src / "stream.jsonl").exists() else src / "stdout"
        if stream.exists():
            shutil.copyfile(stream, dest / "stream.jsonl")
        att.update(judge(family, dest))
    if changed:
        write_meta(meta)
    return changed


def send(family: str) -> str | None:
    """Send the family's next dry run. Returns the job id, or None when Subfleet refused it."""
    meta = read_meta(family)
    attempt = len(meta["attempts"]) + 1
    prompt_path().parent.mkdir(parents=True, exist_ok=True)
    prompt_path().write_text(PROMPT)
    cmd = command(family, attempt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    job_id = None
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            job = obj.get("job") if isinstance(obj.get("job"), dict) else {}
            job_id = obj.get("job_id") or job.get("job_id")
            if job_id:
                break
    if proc.returncode != 0 or not job_id:
        print(f"subfleet refused the {family} dry run (rc {proc.returncode}): {proc.stderr[-400:]}")
        return None
    meta["attempts"].append({"attempt": attempt, "job_id": job_id, "command": cmd, "dispatched_at": store.now(),
                             "state": "submitted"})  # fmt: skip
    write_meta(meta)
    return job_id


def write_public() -> None:
    out = {}
    for fam in design.FAMILIES:
        out[fam] = {
            "standing": standing(fam),
            "attempts": [
                {k: a.get(k) for k in ("attempt", "state", "job_state", "finished_at", "problems", "tool_calls",
                                        "model_served", "attested", "canary", "prior_context_none", "prior_key")}  # fmt: skip
                for a in read_meta(fam)["attempts"]
            ],
        }
    paths.OUTPUTS.mkdir(parents=True, exist_ok=True)
    (paths.OUTPUTS / "dryrun.json").write_text(json.dumps(out, indent=1) + "\n")


def main(family: str | None = None, again: bool = False, show=None) -> int:
    """Collect finished dry runs, then send one for each model that needs it."""
    from . import collect as collect_mod
    from . import dispatch

    show = show or collect_mod.show
    if again and not family:
        print("`--again` sends one model's next dry run: name it with `--family`")
        return 1
    problems = dispatch.sandbox_problems()  # the dry run sends no study text, so the stamp need not exist
    with store.lock():
        for fam in design.FAMILIES:
            if family and fam != family:
                continue
            collect(fam, show)
            s = standing(fam)
            if s == "review":
                print(f"holding {fam}: its dry run's prior_context awaits the blinded reading (cutoff flags)")
            elif s == "held" and not again:
                print(f"holding {fam}: its dry runs failed {MAX_FAILED} times or ended with no answer {MAX_LOST} "
                      f"times; read them in {folder() / fam} and send the next with "
                      f"`cutoff dryrun --family {fam} --again`")  # fmt: skip
            elif s == "due" or (s == "held" and again):
                if problems:
                    for p in problems:
                        print("refusing to send a dry run:", p)
                elif job := send(fam):
                    print(f"sent the {fam} dry run: {job}")
            print(f"{fam} dry run: {standing(fam)}")
        write_public()
    return 0
