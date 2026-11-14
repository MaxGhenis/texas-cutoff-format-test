"""Each model's dry run of the closed setup: what it sends, how it is judged, when it holds, and that
dispatch waits for it. Every record here is MOCK; no test starts a command."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from test_audit import claude_record, codex_record, stream

from cutoff import audit, build, cli, collect, design, dispatch, dryrun, paths, store

GOOD = '```json\n{"product": 391, "prior_context": "none"}\n```'


def meta(family: str, *states, **extra) -> dict:
    """MOCK dry runs of the family's current launch, one per state."""
    sig = dryrun.signature(family)
    return {"family": family, "attempts": [{"attempt": i + 1, "state": s, "signature": sig, **extra} for i, s in enumerate(states)]}


def record(family: str, final: str) -> dict:
    rec = claude_record() if family == "opus" else codex_record()
    sandbox = str(paths.SANDBOX)
    rec["launch"]["cwd"] = sandbox
    if family == "opus":
        rec["launch"]["argv"][rec["launch"]["argv"].index("--add-dir") + 1] = sandbox
        rec["events"][0]["cwd"] = sandbox
        rec["events"][1]["message"]["content"][0]["text"] = final
        rec["events"][2]["result"] = final
    else:
        rec["events"][3]["item"]["text"] = final
    return rec


def write_attempt(folder, family: str, final: str, sent: str = dryrun.PROMPT) -> None:
    rec = record(family, final)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "launch.json").write_text(json.dumps(rec["launch"]))
    (folder / "finalization.json").write_text(json.dumps(rec["fin"]))
    (folder / "stream.jsonl").write_text(stream(rec["events"]))
    (folder / "prompt.sent.md").write_text(sent)


def test_the_prompt_opens_with_the_marker_and_says_nothing_about_the_study():
    assert dryrun.PROMPT.startswith("<!-- subfleet:headless -->\n")
    for word in ("Texas", "governor", "data center", "ERCOT", "Hinojosa", "Abbott", "forecast", build.CANARY_WORD):
        assert word.lower() not in dryrun.PROMPT.lower()


@pytest.mark.parametrize("family", design.FAMILIES)
def test_a_clean_dry_run_passes(family):
    folder = paths.PRIVATE / "MOCK" / family
    write_attempt(folder, family, GOOD)
    rec = dryrun.judge(family, folder)
    assert rec["state"] == "passed", rec["problems"]
    assert rec["prior_context_none"] and not rec["canary"]


@pytest.mark.parametrize(
    "final, sent, problem",
    [
        ('```json\n{"product": 390, "prior_context": "none"}\n```', dryrun.PROMPT, "answer: product 390, not 391"),
        ("MOCK: no JSON", dryrun.PROMPT, "answer: no JSON object"),
        (f'```json\n{{"product": 391, "prior_context": "a note asks for {build.CANARY_WORD}"}}\n```', dryrun.PROMPT,
         "the context wrote the sandbox's code word: it read a folder note"),
        ('```json\n{"product": 391, "prior_context": "  "}\n```', dryrun.PROMPT, "answer: prior_context holds no text"),
        (GOOD, "MOCK headless note\n\n" + dryrun.PROMPT, "the prompt as sent differs from the dry-run prompt"),
    ],
)
@pytest.mark.parametrize("family", design.FAMILIES)
def test_a_faulty_dry_run_fails_with_its_reason(family, final, sent, problem):
    folder = paths.PRIVATE / "MOCK" / family
    write_attempt(folder, family, final, sent)
    rec = dryrun.judge(family, folder)
    assert rec["state"] == "failed" and problem in rec["problems"]


@pytest.mark.parametrize("decision, state", [("clean", "passed"), ("contaminated", "failed")])
def test_a_dry_run_that_reports_prior_context_waits_for_the_blinded_reading(lanes, decision, state):
    dryrun.main(family="opus", show=lambda job_id: None)
    text = "MOCK: a system prompt about tools"
    write_attempt(paths.JOBS / "MOCK-job" / "MOCK-att", "opus", f'```json\n{{"product": 391, "prior_context": "{text}"}}\n```')
    shows = {"MOCK-1": {"job": {"state": "succeeded"}, "attempts": [{"state": "succeeded", "attempt_id": "MOCK-job/MOCK-att"}]}}
    dryrun.main(family="opus", show=shows.get)
    att = dryrun.read_meta("opus")["attempts"][0]
    assert att["state"] == "review" and dryrun.standing("opus") == "review" and not dryrun.passed("opus")
    assert collect.flagged()[att["prior_key"]] == {"text": text, "count": 1, "decision": ""}
    dryrun.main(family="opus", show=shows.get)
    assert len(lanes) == 1  # nothing more goes while the reading is open
    assert collect.decide(att["prior_key"][:10], decision, "MOCK reason") == 0
    dryrun.main(family="opus", show=shows.get)
    assert dryrun.read_meta("opus")["attempts"][0]["state"] == state
    assert dryrun.standing("opus") == ("passed" if decision == "clean" else "held")
    assert len(lanes) == 1  # a contaminated reading holds the model: no second dry run goes by itself
    public = json.loads((paths.OUTPUTS / "dryrun.json").read_text())["opus"]["attempts"][0]
    assert public["prior_key"] == att["prior_key"] and text not in json.dumps(public)
    if decision == "contaminated":
        dryrun.main(family="opus", again=True, show=shows.get)
        assert len(lanes) == 2 and dryrun.standing("opus") == "live"


@pytest.mark.parametrize(
    "states, standing",
    [
        ((), "due"),
        (("submitted",), "live"),
        (("lost", "withdrawn", "lost"), "due"),
        (("failed",), "due"),
        (("failed", "lost", "failed"), "held"),
        (("lost", "withdrawn", "lost", "lost"), "held"),
        (("review",), "review"),
        (("failed", "review"), "review"),
        (("failed", "failed", "passed"), "passed"),
    ],
)
def test_where_a_dry_run_stands(states, standing):
    dryrun.write_meta(meta("sol", *states))
    assert dryrun.standing("sol") == standing


@pytest.fixture
def lanes(monkeypatch):
    """A registration that stands and a Subfleet that accepts every run."""
    monkeypatch.setattr(dispatch, "registration_problems", lambda: [])
    monkeypatch.setattr(dispatch, "sandbox_problems", lambda: [])
    sent = []

    def fake_run(cmd, **kwargs):
        sent.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"job": {"job_id": f"MOCK-{len(sent)}"}}) + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return sent


def test_the_dry_run_goes_through_the_contexts_launch_with_its_own_prompt(lanes):
    assert dryrun.main(show=lambda job_id: None) == 0
    assert len(lanes) == len(design.FAMILIES)
    for cmd, fam in zip(lanes, design.FAMILIES):
        assert cmd[cmd.index("-m") + 1] == design.PIN[fam]
        assert "-I" in cmd and "read-only" in cmd and "--no-needs-shell" in cmd
        assert cmd[cmd.index("-C") + 1] == str(paths.SANDBOX)
        assert cmd[cmd.index("-p") + 1] == str(dryrun.prompt_path())
        assert dryrun.read_meta(fam)["attempts"][0]["job_id"].startswith("MOCK-")
    assert dryrun.prompt_path().read_text() == dryrun.PROMPT
    assert dryrun.main(show=lambda job_id: None) == 0
    assert len(lanes) == len(design.FAMILIES)  # both live: nothing more goes
    public = json.loads((paths.OUTPUTS / "dryrun.json").read_text())
    assert {f: public[f]["standing"] for f in design.FAMILIES} == {f: "live" for f in design.FAMILIES}


def test_a_held_dry_run_waits_for_a_person(lanes, capsys):
    dryrun.write_meta(meta("opus", "failed", "failed"))
    dryrun.main(family="opus", show=lambda job_id: None)
    assert lanes == [] and "holding opus" in capsys.readouterr().out
    dryrun.main(family="opus", again=True, show=lambda job_id: None)
    assert len(lanes) == 1 and dryrun.standing("opus") == "live"


def test_collect_judges_a_finished_dry_run_and_requeues_a_withdrawn_one(lanes):
    dryrun.main(show=lambda job_id: None)
    write_attempt(paths.JOBS / "MOCK-job" / "MOCK-att", "opus", GOOD)
    shows = {
        "MOCK-1": {"job": {"state": "succeeded"}, "attempts": [{"state": "succeeded", "attempt_id": "MOCK-job/MOCK-att"}]},
        "MOCK-2": {"job": {"state": "cancelled"}, "attempts": []},
    }
    dryrun.main(show=shows.get)
    assert dryrun.standing("opus") == "passed"
    sol = dryrun.read_meta("sol")["attempts"]
    assert sol[0]["state"] == "withdrawn" and sol[1]["state"] == "submitted"  # sent again on the same tick
    assert (paths.PRIVATE / "dryrun" / "opus" / "a1" / "final.md").read_text() == GOOD


def test_the_dry_run_launch_is_a_contexts_launch_with_only_its_prompt_name_and_request_id_changed():
    row = next(r for r in store.design_rows() if r["family"] == "sol")
    ctx, dry = dispatch.command(row, 1), dryrun.command("sol", 1)
    swapped = {"-p", "-n", "--request-id"}
    keep = lambda cmd: [x for i, x in enumerate(cmd) if x not in swapped and (i == 0 or cmd[i - 1] not in swapped)]  # noqa: E731
    assert keep(dry) == keep(ctx)
    assert [dry[dry.index(f) + 1] for f in ("-p", "-n")] == [str(dryrun.prompt_path()), "tcf-dryrun-sol"]


def test_the_dry_run_needs_only_the_sandbox_not_the_stamp(lanes, monkeypatch, capsys):
    monkeypatch.setattr(dispatch, "registration_problems", lambda: ["MOCK: no registration"])
    dryrun.main(family="opus", show=lambda job_id: None)
    assert len(lanes) == 1
    monkeypatch.setattr(dispatch, "sandbox_problems", lambda: ["MOCK: the sandbox holds a third file"])
    dryrun.main(family="sol", show=lambda job_id: None)
    assert len(lanes) == 1 and "refusing to send a dry run: MOCK: the sandbox holds a third file" in capsys.readouterr().out


def test_three_dry_runs_with_no_answer_hold_the_model(lanes, capsys):
    for k in range(1, 6):
        dryrun.main(family="opus", show=lambda job_id: {"job": {"state": "failed"}, "attempts": [{"state": "failed"}]})
    states = [a["state"] for a in dryrun.read_meta("opus")["attempts"]]
    assert states == ["lost"] * dryrun.MAX_LOST and dryrun.standing("opus") == "held"
    assert "holding opus" in capsys.readouterr().out


def test_again_needs_a_family(lanes):
    assert dryrun.main(again=True, show=lambda job_id: None) == 1 and lanes == []


def test_a_collected_dry_run_keeps_what_a_context_keeps_and_publishes_no_lane(lanes):
    dryrun.main(family="sol", show=lambda job_id: None)
    src = paths.JOBS / "MOCK-job" / "MOCK-att"
    write_attempt(src, "sol", GOOD)
    (src / "exit.json").write_text("{}")
    show = {"job": {"state": "succeeded", "finished_at": "MOCK-time"},
            "attempts": [{"state": "succeeded", "attempt_id": "MOCK-job/MOCK-att", "lane_id": "MOCK-lane"}]}  # fmt: skip
    dryrun.main(family="sol", show=lambda job_id: show)
    att = dryrun.read_meta("sol")["attempts"][0]
    assert (att["state"], att["lane_id"], att["job_state"], att["finished_at"]) == ("passed", "MOCK-lane", "succeeded", "MOCK-time")
    assert (paths.PRIVATE / "dryrun" / "sol" / "a1" / "exit.json").exists()
    assert "MOCK-lane" not in (paths.OUTPUTS / "dryrun.json").read_text()


def test_a_long_wrong_product_is_cut_in_the_problem():
    problems, _ = dryrun.answer_problems('```json\n{"product": "' + "MOCK" * 50 + '", "prior_context": "none"}\n```')
    assert len(problems[0]) < 80


@pytest.mark.parametrize("due", [False, True])
def test_tick_collects_sends_dry_runs_applies_the_replicate_rule_when_due_then_dispatches(monkeypatch, due):
    from cutoff import analysis

    order = []
    monkeypatch.setattr(collect, "main", lambda: order.append("collect") or 0)
    monkeypatch.setattr(dryrun, "main", lambda: order.append("dryrun") or 0)
    monkeypatch.setattr(analysis, "replicates_due", lambda: due)
    monkeypatch.setattr(analysis, "write_replicates", lambda: order.append("replicates") or 0)
    monkeypatch.setattr(dispatch, "main", lambda: order.append("dispatch") or 0)
    assert cli.main(["tick"]) == 0
    assert order == ["collect", "dryrun", *(["replicates"] if due else []), "dispatch"]


def test_a_pass_counts_only_for_the_launch_and_prompt_it_tried(lanes, monkeypatch):
    dryrun.write_meta(meta("sol", "passed"))
    assert dryrun.passed("sol")
    for target, name, value in (
        (dryrun, "PROMPT", dryrun.PROMPT + "MOCK change\n"),
        (design, "PIN", {**design.PIN, "sol": "MOCK-model"}),
        (build, "CANARY_TEXT", build.CANARY_TEXT + "MOCK change\n"),
    ):
        with monkeypatch.context() as m:
            m.setattr(target, name, value)
            assert not dryrun.passed("sol") and dryrun.standing("sol") == "due", name
    assert dryrun.passed("sol")


def test_dry_runs_of_an_earlier_launch_are_kept_and_judged_but_count_for_nothing(lanes):
    """An earlier launch's dry run still gets collected when its job ends, and judged against the prompt
    it was sent; then it reads `superseded`. Nothing of it holds the model or reaches the reading."""
    earlier = "MOCK-earlier-launch"
    old_prompt = "<!-- subfleet:headless -->\nMOCK earlier dry-run prompt\n"
    key = audit.prior_key("MOCK: an earlier text")
    dryrun.write_meta({"family": "opus", "attempts": [
        {"attempt": 1, "state": "submitted", "job_id": "MOCK-old", "signature": earlier},
        {"attempt": 2, "state": "failed", "job_id": "MOCK-unsigned"},
        {"attempt": 3, "state": "review", "signature": earlier, "prior_key": key},
        {"attempt": 4, "state": "failed", "signature": earlier, "contaminated": True},
        {"attempt": 5, "state": "submitted", "job_id": "MOCK-running", "signature": earlier},
    ]})  # fmt: skip
    text = paths.PRIVATE / "dryrun" / "opus" / "a3"
    text.mkdir(parents=True)
    (text / "prior_context.txt").write_text("MOCK: an earlier text")
    job = paths.JOBS / "MOCK-old"
    write_attempt(job / "a1", "opus", GOOD, sent=old_prompt)
    (job / "prompt.md").write_text(old_prompt)
    shows = {"MOCK-old": {"job": {"state": "succeeded"}, "attempts": [{"state": "succeeded", "attempt_id": "MOCK-old/a1"}]},
             "MOCK-running": {"job": {"state": "running"}, "attempts": []}}  # fmt: skip
    dryrun.main(family="opus", show=shows.get)
    atts = dryrun.read_meta("opus")["attempts"]
    assert [a["state"] for a in atts] == ["superseded", "failed", "superseded", "failed", "submitted", "submitted"]
    assert atts[0]["judged"] == "passed" and atts[0]["problems"] == [] and atts[0]["prior_context_none"] is True
    assert atts[0]["prompt_sha256"] == dryrun.hashlib.sha256(old_prompt.encode()).hexdigest()
    kept = paths.PRIVATE / "dryrun" / "opus" / "a1"
    assert (kept / "final.md").read_text() == GOOD and (kept / "prompt.submitted.md").read_text() == old_prompt
    assert atts[2]["judged"] == "review" and key not in collect.flagged()  # its text never reaches the reading
    assert atts[5]["signature"] == dryrun.signature("opus") and dryrun.standing("opus") == "live"  # the old contaminated flag holds nothing
    assert len(lanes) == 1
    public = json.loads((paths.OUTPUTS / "dryrun.json").read_text())["opus"]
    assert public["signature"] == dryrun.signature("opus")
    assert public["attempts"][0]["judged"] == "passed" and public["attempts"][3]["contaminated"] is True
    assert "lane_id" not in public["attempts"][0] and "MOCK-old" not in json.dumps(public)
    # The earlier run that is still going gets collected when it ends.
    write_attempt(paths.JOBS / "MOCK-running" / "a1", "opus", "MOCK: no JSON", sent=old_prompt)
    (paths.JOBS / "MOCK-running" / "prompt.md").write_text(old_prompt)
    shows["MOCK-running"] = {"job": {"state": "succeeded"}, "attempts": [{"state": "succeeded", "attempt_id": "MOCK-running/a1"}]}
    dryrun.main(family="opus", show=shows.get)
    late = dryrun.read_meta("opus")["attempts"][4]
    assert late["state"] == "superseded" and late["judged"] == "failed" and dryrun.standing("opus") == "live"


@pytest.mark.parametrize("family", design.FAMILIES)
def test_a_code_word_anywhere_in_the_stream_fails_the_dry_run(family):
    """A context that read a folder note can name the word in its reasoning and leave it out of its answer."""
    folder = paths.PRIVATE / "MOCK" / family
    rec = record(family, GOOD)
    if family == "opus":
        rec["events"].insert(1, {"type": "assistant", "message": {"model": audit.CLAUDE_MODEL, "content": [
            {"type": "thinking", "thinking": f"MOCK: a note asks me to write {build.CANARY_WORD}; I will not"}]}})  # fmt: skip
    else:
        rec["events"].insert(2, {"type": "item.completed", "item": {"type": "reasoning", "text": "MOCK: the note says Quillwort 1110"}})
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "launch.json").write_text(json.dumps(rec["launch"]))
    (folder / "finalization.json").write_text(json.dumps(rec["fin"]))
    (folder / "stream.jsonl").write_text(stream(rec["events"]))
    (folder / "prompt.sent.md").write_text(dryrun.PROMPT)
    out = dryrun.judge(family, folder)
    assert out["state"] == "failed" and out["canary"] is True
    assert out["problems"] == ["the context wrote the sandbox's code word: it read a folder note"]


def test_the_signature_covers_the_notes_names_and_not_the_private_store(monkeypatch, tmp_path):
    sig = dryrun.signature("opus")
    with monkeypatch.context() as m:
        m.setattr(build, "CANARY_FILES", (*build.CANARY_FILES, "MOCK.md"))
        assert dryrun.signature("opus") != sig
    with monkeypatch.context() as m:
        m.setattr(paths, "PRIVATE", tmp_path / "MOCK-elsewhere")  # the prompt's path moves; the launch does not
        assert dryrun.signature("opus") == sig
    with monkeypatch.context() as m:
        m.setattr(paths, "SANDBOX", tmp_path / "MOCK-sandbox")  # another folder is another launch
        assert dryrun.signature("opus") != sig
    assert dryrun.signature("sol") != sig


def test_the_readers_rule_covers_dry_runs_and_the_evidence_file_as_the_readme_does():
    rule = collect.READING_RULE
    for phrase in ("in a dry run, anything about arithmetic or a word to write", "declines to describe its provider's system prompt",
                   "ends with an evidence file", "describes or quotes that file restates the prompt",
                   "a note or file in its folder, an instruction from a memory or settings file"):  # fmt: skip
        assert phrase in rule, phrase
    readme = " ".join((paths.ROOT / "README.md").read_text().split())
    for phrase in ("declines to describe its provider's system prompt", "a note or file in its folder, an instruction from a memory or settings file",
                   "describes or quotes that file restates the prompt", "anything about arithmetic or a word to write"):  # fmt: skip
        assert phrase in readme, phrase


def test_the_dry_run_asks_about_what_is_already_in_context_and_takes_a_description():
    flat = " ".join(dryrun.PROMPT.split())
    assert "check what is already in your context other than this prompt" in flat
    assert "describe it in `prior_context`, quoting it if you can" in flat and 'If none of it does, write "none".' in flat
    for arm in ("grid", "alone", "told"):  # rule 8 of each brief asks the same way, about the brief and its evidence file
        brief = " ".join((paths.ROOT / "briefs" / f"{arm}.md").read_text().split())
        assert "check what is already in your context other than this brief and its evidence file" in brief
        assert 'If none of it does, write "none".' in brief


def test_flags_prints_the_readers_rule_above_the_texts(capsys):
    assert cli.main(["flags"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(collect.READING_RULE) and "declines to describe" in out
