"""A dry run of the closed setup for each model, before any study context goes out.

Each model answers one short prompt that has nothing to do with the study: Subfleet's headless marker,
a product to compute, and the study's own `prior_context` rule. The prompt goes through the same
isolated launch as a context (`dispatch.command`) into the same sandbox folder, and the same audit
reads its records. A dry run passes when the audit passes, the prompt as sent matches the dry-run
prompt byte for byte, the answer leaves out the sandbox's code word, and it gives the right product.

Dispatch holds a model until its dry run has passed. A dry run that ends with no answer (a lost or
withdrawn job) goes again; after two failed dry runs, the model stops until a person reads them and
sends the next with `cutoff dryrun --again`. `outputs/dryrun.json` records each attempt's checks; the
records themselves stay in the private store.
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
    """passed, live, held (two failed dry runs and none passed), or due."""
    states = [a["state"] for a in read_meta(family)["attempts"]]
    if "passed" in states:
        return "passed"
    if "submitted" in states:
        return "live"
    if states.count("failed") >= MAX_FAILED:
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
        problems.append(f"answer: product {obj.get('product')!r}, not {PRODUCT}")
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
    return {
        "state": "failed" if problems else "passed",
        "problems": problems,
        "tool_calls": check["tool_calls"],
        "model_served": check["model_served"],
        "attested": check["attested"],
        "canary": canary,
        "prior_context_none": prior is not None and not audit.prior_flag(prior),
    }


def collect(family: str, show) -> bool:
    """Bring the family's submitted dry run up to date. Returns whether anything changed."""
    from .collect import FINISHED

    meta = read_meta(family)
    changed = False
    for att in meta["attempts"]:
        if att["state"] != "submitted":
            continue
        info = show(att["job_id"])
        if info is None or (info.get("job") or {}).get("state") not in FINISHED:
            continue
        done = [a for a in info.get("attempts", []) if a.get("state") == "succeeded"]
        changed = True
        if not done:
            att["state"] = "lost" if info.get("attempts") else "withdrawn"
            continue
        src = paths.JOBS / done[-1]["attempt_id"]
        dest = folder() / family / f"a{att['attempt']}"
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("launch.json", "finalization.json", "prompt.sent.md"):
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
                {k: a.get(k) for k in ("attempt", "state", "problems", "tool_calls", "model_served", "attested",
                                        "canary", "prior_context_none")}  # fmt: skip
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
    problems = dispatch.registration_problems() + dispatch.sandbox_problems()
    with store.lock():
        for fam in design.FAMILIES:
            if family and fam != family:
                continue
            collect(fam, show)
            s = standing(fam)
            if s == "held" and not again:
                print(f"holding {fam}: {MAX_FAILED} dry runs failed; read them in {folder() / fam} and send "
                      f"the next with `cutoff dryrun --family {fam} --again`")  # fmt: skip
            elif s == "due" or (s == "held" and again):
                if problems:
                    for p in problems:
                        print("refusing to send a dry run:", p)
                elif job := send(fam):
                    print(f"sent the {fam} dry run: {job}")
            print(f"{fam} dry run: {standing(fam)}")
        write_public()
    return 0
