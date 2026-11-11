"""Each model's dry run of the closed setup: what it sends, how it is judged, when it holds, and that
dispatch waits for it. Every record here is MOCK; no test starts a command."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from test_audit import claude_record, codex_record, stream

from cutoff import build, cli, collect, design, dispatch, dryrun, paths, store

GOOD = '```json\n{"product": 391, "prior_context": "none"}\n```'


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
         "the answer carries the sandbox's canary word: the context read a project file"),
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
    public = json.loads((paths.OUTPUTS / "dryrun.json").read_text())["opus"]["attempts"][0]
    assert public["prior_key"] == att["prior_key"] and text not in json.dumps(public)


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
    dryrun.write_meta({"family": "sol", "attempts": [{"attempt": i + 1, "state": s} for i, s in enumerate(states)]})
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
    dryrun.write_meta({"family": "opus", "attempts": [{"attempt": 1, "state": "failed"}, {"attempt": 2, "state": "failed"}]})
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


def test_tick_collects_then_sends_dry_runs_then_dispatches(monkeypatch):
    order = []
    monkeypatch.setattr(collect, "main", lambda: order.append("collect") or 0)
    monkeypatch.setattr(dryrun, "main", lambda: order.append("dryrun") or 0)
    monkeypatch.setattr(dispatch, "main", lambda: order.append("dispatch") or 0)
    assert cli.main(["tick"]) == 0
    assert order == ["collect", "dryrun", "dispatch"]
