"""The run's bookkeeping: where a context stands, which may run, what dispatch sends, and what collect
makes of a finished attempt. Every record here is MOCK; no test starts a command."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest
from test_audit import claude_record, stream
from test_response import answer, fenced

from cutoff import build, collect, design, dispatch, paths, registration, store
from cutoff.jump import KEYS, QUESTIONS

ROWS = store.design_rows()
REAL_SANDBOX_PROBLEMS = dispatch.sandbox_problems  # read at import, before any fixture stubs it


def meta(*states):
    return {"context": "MOCK", "attempts": [{"attempt": i + 1, "state": s} for i, s in enumerate(states)]}


@pytest.mark.parametrize(
    "states, status",
    [
        ((), "due"),
        (("submitted",), "live"),
        (("review",), "review"),
        (("failed",), "due"),
        (("failed", "failed", "failed"), "stopped"),
        (("lost",) * 4, "due"),
        (("lost",) * 5, "stopped"),
        (("failed", "passed"), "passed"),
        (("failed", "submitted"), "live"),
        (("lost", "lost", "failed", "failed"), "due"),
        (("withdrawn",) * 9, "due"),
        (("lost",) * 4 + ("withdrawn",) * 3, "due"),
        (("failed", "failed", "withdrawn", "failed"), "stopped"),
    ],
)
def test_where_a_context_stands(states, status):
    assert store.summary(meta(*states))["status"] == status


# ----------------------------------------------------------------------------------------- eligibility


def metas_with(states: dict) -> dict:
    return {r["context"]: meta(*states.get(r["context"], ())) for r in ROWS}


def test_only_wave_1_may_run_at_first_and_wave_3_waits_for_the_replicate_rule():
    out = dispatch.eligible(ROWS, metas_with({}))
    assert {r["wave"] for r in out} == {1} and len(out) == 156


def test_a_familys_wave_2_waits_for_its_own_wave_1_and_a_reading_does_not_hold_it(monkeypatch):
    opus1 = {r["context"]: ("passed",) for r in ROWS if r["wave"] == 1 and r["family"] == "opus"}
    out = dispatch.eligible(ROWS, metas_with(opus1))
    assert {(r["wave"], r["family"]) for r in out} == {(1, "sol"), (2, "opus")}
    sol1 = {r["context"]: ("review",) for r in ROWS if r["wave"] == 1 and r["family"] == "sol"}
    out = dispatch.eligible(ROWS, metas_with({**opus1, **sol1}))
    assert {(r["wave"], r["family"]) for r in out} == {(2, "opus"), (2, "sol")}
    done = {r["context"]: ("passed",) for r in ROWS if r["wave"] < 3}
    assert dispatch.eligible(ROWS, metas_with(done)) == []
    monkeypatch.setattr(dispatch, "replicates_allowed", lambda: 4)
    out = dispatch.eligible(ROWS, metas_with(done))
    assert {r["replicate"] for r in out} == {4} and len(out) == 416


# ------------------------------------------------------------------------------------------ registration


def test_no_registration_means_no_dispatch():
    assert dispatch.registration_problems() == ["no registration: prereg/registration/SHA256SUMS is missing"]


def write_manifest(names, change=None):
    registration.REGISTRATION.mkdir(parents=True, exist_ok=True)
    lines = []
    for rel in names:
        p = paths.ROOT / rel
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "0" * 64
        lines.append(f"{change(rel, digest) if change else digest}  {rel}")
    (registration.REGISTRATION / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def mock_stamp() -> None:
    """A MOCK proof shaped like OpenTimestamps': its header, then the SHA-256 of the list as it stands."""
    digest = hashlib.sha256((registration.REGISTRATION / "SHA256SUMS").read_bytes()).digest()
    (registration.REGISTRATION / "SHA256SUMS.ots").write_bytes(registration.OTS_MAGIC + b"\x01\x08" + digest + b"MOCK")


def test_a_registration_that_matches_needs_only_its_stamp():
    write_manifest(registration.STIMULUS)
    assert dispatch.registration_problems() == ["the registration has no OpenTimestamps stamp (SHA256SUMS.ots)"]
    mock_stamp()
    assert dispatch.registration_problems() == []


def test_a_changed_or_missing_stimulus_file_is_a_problem_not_a_crash(monkeypatch):
    names = (*registration.STIMULUS, "briefs/MOCK-missing.md")
    monkeypatch.setattr(registration, "STIMULUS", names)
    write_manifest(names, lambda rel, d: "f" * 64 if rel == "briefs/grid.md" else d)
    mock_stamp()
    assert sorted(dispatch.registration_problems()) == [
        "briefs/MOCK-missing.md is missing",
        "briefs/grid.md changed since the registration",
    ]


def test_changes_lists_every_registered_file_that_differs_and_the_records_that_name_it(monkeypatch):
    names = ("src/cutoff/jump.py", "src/cutoff/analysis.py", "design/reference.json", "MOCK/missing.txt")
    write_manifest(names, lambda rel, d: "f" * 64 if rel in ("src/cutoff/jump.py", "src/cutoff/analysis.py") else d)
    assert registration.changes()["stamped"] is False
    mock_stamp()
    mark = registration.sha(paths.ROOT / "src/cutoff/jump.py")[:12]
    (registration.REGISTRATION.parent / "2026-12-01-MOCK.md").write_text(f"MOCK: we changed src/cutoff/jump.py (now {mark}) because ...")
    # A record that names a file without its present hash covers an earlier change, not this one.
    (registration.REGISTRATION.parent / "2026-11-20-MOCK.md").write_text("MOCK: src/cutoff/analysis.py (now 000000000000) changed")
    ch = registration.changes()
    assert ch["stamped"] and [c["file"] for c in ch["changed"]] == ["MOCK/missing.txt", "src/cutoff/analysis.py", "src/cutoff/jump.py"]
    by_file = {c["file"]: c for c in ch["changed"]}
    assert by_file["MOCK/missing.txt"]["state"] == "missing"
    assert by_file["src/cutoff/jump.py"]["deviations"] == ["prereg/2026-12-01-MOCK.md"]
    assert by_file["src/cutoff/analysis.py"]["deviations"] == []
    text = "\n".join(registration.describe(ch))
    assert "3 registered files differ" in text and "NO DEVIATION RECORD NAMES IT" in text
    assert registration.unrecorded(ch) == ["MOCK/missing.txt", "src/cutoff/analysis.py"]
    # A file that is gone needs a record that says so; a record of an earlier change does not cover it.
    (registration.REGISTRATION.parent / "2026-12-03-MOCK.md").write_text("MOCK: MOCK/missing.txt changed (now 000000000000)")
    assert "MOCK/missing.txt" in registration.unrecorded(registration.changes())
    (registration.REGISTRATION.parent / "2026-12-04-MOCK.md").write_text("MOCK: MOCK/missing.txt removed, because ...")
    assert registration.unrecorded(registration.changes()) == ["src/cutoff/analysis.py"]


def test_the_analysis_reports_changed_files_and_never_a_clean_bill_without_a_list():
    assert registration.describe(registration.changes()) == ["Registration: none found (prereg/registration/SHA256SUMS is missing)."]
    write_manifest(("src/cutoff/jump.py",))
    mock_stamp()
    assert registration.describe(registration.changes()) == [
        "Registration: stamped, and the list matches its proof.",
        "Every registered file matches the list, and the list covers every registered file.",
    ]


def test_the_proof_binds_the_list(capsys):
    """After the stamp nobody can edit, rewrite or remove the list without every check saying so."""
    from cutoff import cli

    write_manifest(registration.STIMULUS)
    mock_stamp()
    assert dispatch.registration_problems() == [] and cli.main(["registration", "--check"]) == 0
    listed = registration.REGISTRATION / "SHA256SUMS"
    original = listed.read_text()
    # An edited line with a matching file: the files agree with the list, and the list no longer agrees with its proof.
    listed.write_text(original + "f" * 64 + "  MOCK/added-later.txt\n")
    assert "SHA256SUMS differs from the list its OpenTimestamps proof stamps" in dispatch.registration_problems()
    assert cli.main(["registration", "--check"]) == 1 and "NOT STAMPED" in capsys.readouterr().out
    listed.write_text(original)
    (registration.REGISTRATION / "SHA256SUMS.ots").write_bytes(b"MOCK not a proof")
    assert dispatch.registration_problems() == ["SHA256SUMS.ots does not read as an OpenTimestamps proof of a SHA-256"]
    mock_stamp()
    listed.unlink()  # the list removed, its proof left behind
    assert cli.main(["registration", "--check"]) == 1 and "the proof stands without its list" in capsys.readouterr().out
    assert dispatch.registration_problems() == ["no registration: prereg/registration/SHA256SUMS is missing"]


def test_a_line_the_list_cannot_read_is_a_problem_not_a_crash():
    write_manifest(registration.STIMULUS)
    listed = registration.REGISTRATION / "SHA256SUMS"
    listed.write_text(listed.read_text() + "MOCK line with no digest\n")
    mock_stamp()
    ch = registration.changes()
    assert [c["file"] for c in ch["changed"]] == [f"unreadable line {len(registration.STIMULUS) + 1}"] and registration.unrecorded(ch)


REAL_SCOPE = registration.SCOPE  # read at import, before the fixture empties it


def test_the_list_covers_every_registered_file_and_is_written_once(monkeypatch):
    monkeypatch.setattr(registration, "SCOPE", REAL_SCOPE)
    # With the replicate rule's record and a stray file in the tree, the list still holds neither.
    tracked = subprocess_git(["ls-files", "-z"]) if (paths.ROOT / ".git").exists() else None
    with_extras = None if tracked is None else [*tracked, "design/replicates.json"]
    monkeypatch.setattr(registration, "_tracked", lambda: with_extras)
    assert "design/replicates.json" not in registration.scope()
    monkeypatch.setattr(registration, "AFTER_THE_STAMP", ())
    if tracked is not None and not (paths.ROOT / "design" / "replicates.json").exists():
        assert "design/replicates.json" not in registration.scope()  # not a file yet: the list names only what exists
    monkeypatch.setattr(registration, "AFTER_THE_STAMP", ("design/replicates.json", "README.md"))
    assert "README.md" not in registration.scope()  # the exclusion works on a file that exists
    monkeypatch.setattr(registration, "AFTER_THE_STAMP", ("design/replicates.json",))
    monkeypatch.setattr(registration, "_tracked", lambda: tracked)
    files = registration.write_list()
    listed = registration.manifest()
    assert sorted(listed) == files == registration.scope()
    for rel in (*registration.STIMULUS, "README.md", "pyproject.toml", "uv.lock", "outputs/power.md", "src/cutoff/analysis.py",
                "src/cutoff/registration.py", "scripts/make_briefs.py", "tests/test_analysis.py", "design/reference.json",
                ".github/workflows/ci.yml"):  # fmt: skip
        assert listed[rel] == registration.sha(paths.ROOT / rel), rel
    assert "design/replicates.json" not in listed and not any("__pycache__" in rel or rel.endswith(".pyc") for rel in listed)
    lines = (registration.REGISTRATION / "SHA256SUMS").read_text().splitlines()
    assert all(len(line.split("  ", 1)[0]) == 64 for line in lines)  # `shasum -a 256 -c` reads this form
    assert registration.changes()["changed"] == []
    with pytest.raises(SystemExit, match="exists already"):
        registration.write_list()
    if tracked is not None:  # every tracked file in the registered folders is on the list, and nothing else
        want = subprocess_git(["ls-files", "-z", "README.md", "pyproject.toml", "uv.lock", "outputs/power.md", ".github/workflows/ci.yml",
                               "briefs", "design", "src", "scripts", "tests"])  # fmt: skip
        assert sorted(set(want) - set(registration.AFTER_THE_STAMP)) == files
        assert not any(name.split("/")[-1].startswith(".") or "__pycache__" in name for name in files)


def test_the_list_refuses_to_leave_out_a_stimulus_file(monkeypatch):
    monkeypatch.setattr(registration, "SCOPE", REAL_SCOPE)
    monkeypatch.setattr(registration, "STIMULUS", (*registration.STIMULUS, "briefs/MOCK-missing.md"))
    with pytest.raises(SystemExit, match="stimulus files are missing"):
        registration.write_list()
    assert not (registration.REGISTRATION / "SHA256SUMS").exists()


def test_without_git_the_scope_skips_hidden_and_cache_files(monkeypatch):
    monkeypatch.setattr(registration, "SCOPE", REAL_SCOPE)
    monkeypatch.setattr(registration, "_tracked", lambda: None)
    files = registration.scope()
    assert "README.md" in files and "src/cutoff/analysis.py" in files and ".github/workflows/ci.yml" in files
    assert not any("__pycache__" in name or name.endswith(".pyc") or "/." in name.replace(".github/", "") for name in files)
    assert not any(name.startswith((".venv/", ".git/", ".hypothesis/", ".pytest_cache/")) for name in files)


def subprocess_git(args: list[str]) -> list[str]:
    # One read-only `git ls-files`. The fixture stubs subprocess.run, so it goes through Popen.
    out, _ = subprocess.Popen(["git", "-C", str(paths.ROOT), *args], stdout=subprocess.PIPE).communicate()
    return [name for name in out.decode().split("\0") if name]


def test_a_registered_file_the_list_lacks_is_reported_until_a_record_names_it(monkeypatch, capsys):
    monkeypatch.setattr(registration, "SCOPE", REAL_SCOPE)
    from cutoff import cli

    assert cli.main(["registration", "--check"]) == 0 and "none found" in capsys.readouterr().out  # before the stamp
    write_manifest([rel for rel in registration.scope() if rel != "src/cutoff/analysis.py"])
    mock_stamp()
    ch = registration.changes()
    assert ch["changed"] == [{"file": "src/cutoff/analysis.py", "state": "unlisted", "deviations": []}]
    assert dispatch.registration_problems() == []  # the stimulus still matches
    assert cli.main(["registration", "--check"]) == 1 and "NO DEVIATION RECORD NAMES IT" in capsys.readouterr().out
    mark = registration.sha(paths.ROOT / "src/cutoff/analysis.py")[:12]
    (registration.REGISTRATION.parent / "2026-12-02-MOCK.md").write_text(f"MOCK: src/cutoff/analysis.py {mark} joined the list late")
    assert cli.main(["registration", "--check"]) == 0
    assert cli.main(["registration"]) == 0


# ------------------------------------------------------------------------------------------- dispatch


@pytest.fixture
def ready(monkeypatch):
    """A registration that stands, and MOCK prompt files whose hashes the design table gives."""
    monkeypatch.setattr(dispatch, "registration_problems", lambda: [])
    monkeypatch.setattr(dispatch, "sandbox_problems", lambda: [])
    monkeypatch.setattr(dispatch.dryrun, "passed", lambda family: True)
    folder = paths.PRIVATE / "prompts"
    folder.mkdir(parents=True)
    hashes = {}
    for pid in {r["prompt"] for r in ROWS}:
        body = f"MOCK prompt {pid}\n"
        (folder / f"{pid}.md").write_text(body)
        hashes[pid] = hashlib.sha256(body.encode()).hexdigest()
    monkeypatch.setattr(dispatch, "prompt_hashes", lambda: hashes)
    sent = []

    def fake_run(cmd, **kwargs):
        sent.append(cmd)
        out = '[1, 2]\n"MOCK"\nnot json\n' + json.dumps({"job": {"job_id": f"MOCK-{len(sent)}"}}) + "\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return sent


def pass_one(family: str) -> dict:
    """Mark the family's last wave-1 context passed, so the pilot rule lets the family run in full."""
    r = [x for x in ROWS if x["wave"] == 1 and x["family"] == family][-1]
    store.write_meta({"context": r["context"], "attempts": [{"attempt": 1, "state": "passed"}]})
    return r


def test_dispatch_sends_wave_1_in_order_and_records_each_job(ready):
    pass_one("opus")
    assert dispatch.main(family="opus", limit=2) == 0
    first = [r for r in ROWS if r["wave"] == 1 and r["family"] == "opus"][:2]
    assert [c[c.index("-n") + 1] for c in ready] == [r["name"] for r in first]
    for k, r in enumerate(first, 1):
        m = store.read_meta(r["context"])
        assert m["attempts"][0]["job_id"] == f"MOCK-{k}" and m["attempts"][0]["state"] == "submitted"
        cmd = ready[k - 1]
        assert cmd[cmd.index("-m") + 1] == design.PIN["opus"] and "-I" in cmd and "read-only" in cmd
        assert cmd[cmd.index("--request-id") + 1] == r["request_id"]


def test_dispatch_keeps_each_family_within_its_in_flight_limit(ready):
    for fam in design.FAMILIES:
        pass_one(fam)
    assert dispatch.main() == 0
    assert len(ready) == 2 * dispatch.MAX_IN_FLIGHT
    assert dispatch.main() == 0
    assert len(ready) == 2 * dispatch.MAX_IN_FLIGHT  # nothing finished, so no room


def test_a_family_runs_one_context_at_a_time_until_one_passes(ready):
    assert dispatch.main() == 0
    assert len(ready) == len(design.FAMILIES)  # one each
    assert dispatch.main() == 0
    assert len(ready) == len(design.FAMILIES)  # each pilot still live
    pass_one("opus")
    assert dispatch.main() == 0
    assert len(ready) == len(design.FAMILIES) + dispatch.MAX_IN_FLIGHT - 1  # opus fills; its pilot is live


def test_two_failures_with_no_pass_hold_the_family_until_sent_by_hand(ready, capsys):
    sol = [r for r in ROWS if r["wave"] == 1 and r["family"] == "sol"]
    store.write_meta({"context": sol[0]["context"], "attempts": [{"attempt": 1, "state": "failed"}, {"attempt": 2, "state": "failed"}]})
    assert dispatch.main(family="sol") == 0
    assert ready == [] and "holding sol: 2 failed answers and 0 runs with no answer" in capsys.readouterr().out
    assert dispatch.main(family="sol", limit=1, pilot_ok=True) == 0
    assert len(ready) == 1
    assert dispatch.main(family="sol", pilot_ok=True) == 0
    assert len(ready) == 1  # the hand-sent pilot is live, so no room


@pytest.mark.parametrize(
    "spread, held",
    [
        ({0: ("lost", "withdrawn", "lost", "failed")}, False),  # two lost and one failed
        ({0: ("withdrawn",) * 9}, False),  # withdrawn jobs never ran
        ({0: ("lost", "lost"), 1: ("lost",)}, True),  # three lost, across contexts
        ({0: ("failed",), 1: ("failed",)}, True),
        ({0: ("lost",) * 5, 1: ("passed",)}, False),  # a pass ends the pilot
        ({0: ("review",)}, True),  # a first answer that awaits the reading
        ({0: ("review",), 1: ("passed",)}, False),
    ],
)
def test_the_pilot_holds_a_family_after_two_failed_answers_or_three_runs_with_no_answer(spread, held):
    rows = [r for r in ROWS if r["family"] == "opus"]
    metas = {r["context"]: meta() for r in ROWS}
    for i, states in spread.items():
        metas[rows[i]["context"]] = meta(*states)
    cap, why, by_hand = dispatch.pilot(ROWS, metas, "opus")
    passed = any("passed" in states for states in spread.values())
    assert (cap, why is not None) == ((0, True) if held else (dispatch.MAX_IN_FLIGHT if passed else 1, False))
    waits_for_reading = held and any("review" in states for states in spread.values())
    assert by_hand == (held and not waits_for_reading)  # the reading lifts that wait; `--pilot` cannot


def test_a_setup_that_loses_every_run_costs_three_runs_not_a_wave(ready, capsys):
    """The delta review's counterexample: every opus run ends with no answer, tick after tick."""
    for _ in range(15):
        dispatch.main(family="opus")
        for r in ROWS:
            m = store.read_meta(r["context"])
            if m["attempts"] and m["attempts"][-1]["state"] == "submitted":
                m["attempts"][-1]["state"] = "lost"
                store.write_meta(m)
    assert len(ready) == dispatch.PILOT_LOST
    assert "holding opus: 0 failed answers and 3 runs with no answer" in capsys.readouterr().out


def test_a_first_answer_in_review_holds_the_family_until_the_reading(ready, capsys):
    """Round 2's counterexample: every opus answer lands in review, tick after tick."""
    for _ in range(15):
        dispatch.main(family="opus")
        for r in ROWS:
            m = store.read_meta(r["context"])
            if m["attempts"] and m["attempts"][-1]["state"] == "submitted":
                m["attempts"][-1]["state"] = "review"
                store.write_meta(m)
    assert len(ready) == 1
    assert "holding opus: its first answer awaits the blinded reading" in capsys.readouterr().out
    dispatch.main(family="opus", limit=1, pilot_ok=True)
    assert len(ready) == 1 and "holding opus: its first answer awaits" in capsys.readouterr().out  # `--pilot` waits too
    # Two failed answers beside the one in review: the reading still comes first, and `--pilot` cannot lift it.
    others = [r for r in ROWS if r["family"] == "opus" and not store.read_meta(r["context"])["attempts"]][:2]
    for r in others:
        store.write_meta({"context": r["context"], "attempts": [{"attempt": 1, "state": "failed"}]})
    dispatch.main(family="opus", limit=1, pilot_ok=True)
    assert len(ready) == 1 and "awaits the blinded reading" in capsys.readouterr().out


def test_dispatch_refuses_while_the_sandbox_holds_a_third_file(ready, monkeypatch, isolated_store, capsys):
    # The `ready` fixture stubs the sandbox check; put the real one back. The store's own patches stay,
    # so this writes to the test's temporary sandbox and never to the real one.
    monkeypatch.setattr(dispatch, "sandbox_problems", REAL_SANDBOX_PROBLEMS)
    assert str(paths.SANDBOX).startswith(str(isolated_store))
    paths.SANDBOX.mkdir(parents=True, exist_ok=True)
    for name in build.CANARY_FILES:
        (paths.SANDBOX / name).write_text(build.CANARY_TEXT)
    (paths.SANDBOX / "MOCK-third.md").write_text("MOCK")
    assert dispatch.main() == 1 and "refusing to dispatch: the sandbox holds" in capsys.readouterr().out
    assert ready == []
    (paths.SANDBOX / "MOCK-third.md").unlink()
    pass_one("opus")
    assert dispatch.main(family="opus", limit=1) == 0 and len(ready) == 1  # the same call goes once the folder is clean


@pytest.mark.parametrize("pilot_ok", [False, True])
def test_dispatch_sends_only_for_models_whose_dry_run_passed(ready, monkeypatch, capsys, pilot_ok):
    pass_one("opus")
    pass_one("sol")
    monkeypatch.setattr(dispatch.dryrun, "passed", lambda family: family == "opus")
    assert dispatch.main(pilot_ok=pilot_ok) == 0
    assert ready and all(c[c.index("-m") + 1] == design.PIN["opus"] for c in ready)
    assert "holding sol: its dry run has not passed" in capsys.readouterr().out


def test_dispatch_sends_nothing_when_any_due_prompt_file_differs(ready):
    first = next(r for r in ROWS if r["wave"] == 1)
    (paths.PRIVATE / "prompts" / f"{first['prompt']}.md").write_text("MOCK changed\n")
    assert dispatch.main() == 1
    assert ready == []


def test_a_later_attempt_gets_its_own_request_id_and_name(ready):
    pass_one("sol")
    r = next(x for x in ROWS if x["wave"] == 1 and x["family"] == "sol")
    store.write_meta({"context": r["context"], "attempts": [{"attempt": 1, "state": "failed"}]})
    dispatch.main(family="sol", limit=1)
    cmd = ready[0]
    assert cmd[cmd.index("-n") + 1] == f"{r['name']}-a2"
    assert cmd[cmd.index("--request-id") + 1] == dispatch.request_id(r["context"], 2) != r["request_id"]


# -------------------------------------------------------------------------------------------- collect

GRID = next(r for r in ROWS if r["family"] == "opus" and r["arm"] == "grid")


def attempt_folder(final: str, row=GRID, lead: str = "", earlier: str = "") -> object:
    registered = f"MOCK registered prompt for {row['prompt']}\n"
    (paths.PRIVATE / "prompts").mkdir(parents=True, exist_ok=True)
    (paths.PRIVATE / "prompts" / f"{row['prompt']}.md").write_text(registered)
    rec = claude_record()
    sandbox = str(paths.SANDBOX)
    rec["launch"]["cwd"] = sandbox
    rec["launch"]["argv"][rec["launch"]["argv"].index("--add-dir") + 1] = sandbox
    rec["events"][0]["cwd"] = sandbox
    rec["events"][1]["message"]["content"][0]["text"] = final
    rec["events"][2]["result"] = final
    if earlier:  # a message before the answer
        rec["events"].insert(1, {"type": "assistant", "message": {"model": rec["events"][1]["message"]["model"],
                                                                  "content": [{"type": "text", "text": earlier}]}})  # fmt: skip
    folder = store.contexts_dir() / row["context"] / "a1"
    folder.mkdir(parents=True)
    (folder / "launch.json").write_text(json.dumps(rec["launch"]))
    (folder / "finalization.json").write_text(json.dumps(rec["fin"]))
    (folder / "stream.jsonl").write_text(stream(rec["events"]))
    (folder / "prompt.sent.md").write_text(lead + registered)
    return folder


def test_a_clean_answer_passes():
    rec = collect.judge(GRID, attempt_folder(fenced(answer())))
    assert rec["state"] == "passed", rec["problems"]
    assert rec["repairs"] == 0 and rec["prior_key"] is None and rec["canary"] is False


def test_a_note_ahead_of_the_registered_prompt_fails_the_context():
    rec = collect.judge(GRID, attempt_folder(fenced(answer()), lead="MOCK headless note\n\n"))
    assert rec["state"] == "failed" and "the prompt as sent differs from the registered prompt" in rec["problems"]
    assert rec["lead_sha256"]


def test_an_answer_that_fails_the_check_fails():
    rec = collect.judge(GRID, attempt_folder("MOCK: no JSON here"))
    assert rec["state"] == "failed" and any(p.startswith("answer:") for p in rec["problems"])


def test_an_answer_with_the_canary_word_fails():
    a = answer(prior=f"The folder note asked me to write {build.CANARY_WORD}.")
    rec = collect.judge(GRID, attempt_folder(fenced(a)))
    assert rec["state"] == "failed" and rec["canary"] is True


def test_a_context_that_names_the_code_word_before_its_answer_fails():
    """The check reads the whole kept stream: here the answer says "none" and an earlier message names the word."""
    rec = collect.judge(GRID, attempt_folder(fenced(answer()), earlier="MOCK: a folder note asks for Quillwort 1110; I will leave it out"))
    assert rec["state"] == "failed" and rec["canary"] is True
    assert rec["problems"] == ["the context wrote the sandbox's code word: it read a folder note"]



def test_a_prior_context_waits_for_the_reading_and_a_decision_stands():
    text = "MOCK: I remember a news story about the pause."
    rec = collect.judge(GRID, attempt_folder(fenced(answer(prior=text))))
    assert rec["state"] == "review" and rec["prior_key"]
    store.write_meta({"context": GRID["context"], "attempts": [{"attempt": 1, "job_id": "MOCK", **rec}]})
    flagged = collect.flagged()
    assert list(flagged) == [rec["prior_key"]] and flagged[rec["prior_key"]]["text"] == text
    reader = "MOCK-model, Subfleet job MOCK-1, attested"
    # The reason and the reader go to a public file: no quote from the text, no path, no missing reader.
    assert collect.decide(rec["prior_key"][:10], "clean", "it says: I remember a news story about the pause", reader) == 1
    assert collect.decide(rec["prior_key"][:10], "clean", "  ", reader) == 1
    assert collect.decide(rec["prior_key"][:10], "clean", "MOCK: general knowledge") == 1
    assert collect.decide(rec["prior_key"][:10], "clean", "MOCK: general knowledge", "a reader at /Users/MOCK-lane") == 1
    assert collect.prior_decisions() == {}
    assert collect.decide(rec["prior_key"][:10], "clean", "MOCK: general knowledge", reader) == 0
    assert collect.decide(rec["prior_key"][:10], "contaminated", "MOCK: changed mind", reader) == 1
    with collect.PRIOR_REVIEW.open() as fh:
        public = list(csv.DictReader(fh))
    assert [r["decision"] for r in public] == ["clean"] and "text" not in public[0]
    assert public[0]["reader"] == reader and list(public[0]) == ["key", "decision", "reason", "reader", "read_at"]
    assert text in (paths.PRIVATE / "review" / "prior_context_texts.csv").read_text()
    att = store.read_meta(GRID["context"])["attempts"][0]
    assert collect.rejudge(GRID, store.read_meta(GRID["context"]), att) and att["state"] == "passed"


def test_tables_hold_each_passed_attempts_answers_and_every_attempt():
    rec = collect.judge(GRID, attempt_folder(fenced(answer())))
    store.write_meta({"context": GRID["context"], "attempts": [{"attempt": 1, "job_id": "MOCK", **rec}]})
    n_answers, n_attempts = collect.write_tables()
    assert (n_answers, n_attempts) == (len(QUESTIONS) * len(KEYS), 1)
    with (paths.OUTPUTS / "answers.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert {r["context"] for r in rows} == {GRID["context"]}
    assert {float(r["value"]) for r in rows if r["question"] == "ercot_pause_lifted"} == {40.0}


@pytest.mark.parametrize("lane_attempts, state", [([], "withdrawn"), ([{"state": "failed"}], "lost")])
def test_a_job_that_ends_with_no_answer_is_lost_only_if_a_lane_started_it(monkeypatch, lane_attempts, state):
    info = {"job": {"state": "cancelled", "finished_at": "MOCK"}, "attempts": lane_attempts}
    monkeypatch.setattr(collect, "show", lambda job_id: info)
    meta = {"context": GRID["context"], "attempts": [{"attempt": 1, "job_id": "MOCK", "state": "submitted"}]}
    assert collect.collect_attempt(GRID, meta, meta["attempts"][0])
    assert meta["attempts"][0]["state"] == state
    assert store.summary(meta)["status"] == "due"


def test_the_replicate_rule_waits_for_every_first_batch_reading(monkeypatch, capsys):
    from cutoff import analysis

    monkeypatch.setattr(store, "design_rows", lambda: ROWS)
    monkeypatch.setattr(paths, "DESIGN", paths.OUTPUTS)
    wave1 = [r for r in ROWS if r["wave"] == 1]
    for r in wave1:
        store.write_meta({"context": r["context"], "attempts": [{"attempt": 1, "state": "passed"}]})
    store.write_meta({"context": wave1[0]["context"], "attempts": [{"attempt": 1, "state": "review"}]})
    assert analysis.write_replicates() == 1
    assert "1 of 156 contexts still running or awaiting a reading" in capsys.readouterr().out
    assert not (paths.OUTPUTS / "replicates.json").exists()
