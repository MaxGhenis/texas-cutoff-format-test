"""The audit of a closed context, on MOCK records shaped like the ones Subfleet keeps: a clean record
passes, and each single defect fails it."""

from __future__ import annotations

import copy
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cutoff import audit

SANDBOX = "/MOCK/sandbox"
FINAL = "MOCK final answer"


def claude_record():
    # The shape of a real launch under Subfleet's isolated mode, with MOCK values.
    argv = ["claude", "-p", "--model", audit.CLAUDE_MODEL, "--session-id", "MOCK-session", "--output-format", "stream-json",
            "--verbose", "--permission-mode", "plan", "--tools", "Read,Glob,Grep", "--allowedTools", "Read,Glob,Grep",
            "--setting-sources", "", "--safe-mode", "--no-chrome", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands", "--add-dir", SANDBOX, "--settings", '{"env":{"MOCK_WATCHDOG":"0"}}']  # fmt: skip
    events = [
        {"type": "system", "subtype": "init", "model": audit.CLAUDE_MODEL, "tools": ["Read", "Glob", "Grep"],
         "mcp_servers": [], "cwd": SANDBOX},
        {"type": "assistant", "message": {"model": audit.CLAUDE_MODEL, "content": [{"type": "text", "text": FINAL}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": FINAL,
         "modelUsage": {audit.CLAUDE_MODEL: {"inputTokens": 1}}},
    ]  # fmt: skip
    fin = {"attestation": {"status": "attested", "served_model": audit.CLAUDE_MODEL}}
    return {"events": events, "launch": {"argv": argv, "cwd": SANDBOX}, "fin": fin}


def codex_record():
    # The shape of a real launch under Subfleet's isolated mode, with MOCK values.
    argv = ["codex", "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "-c", "project_doc_max_bytes=0", "-c", "features.apps=false", "-c", "features.hooks=false",
            "-c", "features.multi_agent=false", "-c", "features.multi_agent_v2=false", "-c", "features.memories=false",
            "-c", "shell_environment_policy.experimental_use_profile=false", "-c", 'history.persistence="none"',
            "-c", 'web_search="disabled"', "-m", audit.CODEX_MODEL, "-c", f"model_reasoning_effort={audit.CODEX_EFFORT}",
            "--sandbox", "read-only", "--output-last-message", "/MOCK/job/last.md"]  # fmt: skip
    events = [
        {"type": "thread.started", "thread_id": "MOCK"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "MOCK"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": FINAL}},
        {"type": "turn.completed", "usage": {}},
    ]
    fin = {"outcome": {"cls": "ok"}, "attestation": {"status": "unattested"}}
    return {"events": events, "launch": {"argv": argv, "cwd": SANDBOX}, "fin": fin}


def stream(events) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def run(kind, rec):
    fn = audit.claude if kind == "claude" else audit.codex
    return fn(stream(rec["events"]), rec["launch"], rec["fin"], SANDBOX)


def of_type(events, kind, subtype=None):
    return next(e for e in events if e["type"] == kind and (subtype is None or e.get("subtype") == subtype))


def set_after(argv, flag, value):
    argv[argv.index(flag) + 1] = value


CLAUDE_DEFECTS = {
    "another model": lambda r: set_after(r["launch"]["argv"], "--model", "claude-haiku-5-5"),
    "a shell tool": lambda r: set_after(r["launch"]["argv"], "--tools", "Read,Bash"),
    "settings loaded": lambda r: set_after(r["launch"]["argv"], "--setting-sources", "user"),
    "no safe mode": lambda r: r["launch"]["argv"].remove("--safe-mode"),
    "not plan mode": lambda r: set_after(r["launch"]["argv"], "--permission-mode", "default"),
    "another folder": lambda r: r["launch"].update(cwd="/MOCK/elsewhere"),
    "an MCP server": lambda r: of_type(r["events"], "system", "init").update(mcp_servers=[{"name": "MOCK"}]),
    "init names another model": lambda r: of_type(r["events"], "system", "init").update(model="claude-opus-4-8"),
    "a tool call": lambda r: of_type(r["events"], "assistant")["message"]["content"].append({"type": "tool_use", "name": "Read"}),
    "a message from another model": lambda r: r["events"].insert(-1, {"type": "assistant", "message": {"model": "claude-haiku-5-5", "content": []}}),
    "an error result": lambda r: of_type(r["events"], "result").update(is_error=True),
    "usage from two models": lambda r: of_type(r["events"], "result")["modelUsage"].update({"claude-haiku-5-5": {}}),
    "two init events": lambda r: r["events"].insert(0, copy.deepcopy(of_type(r["events"], "system", "init"))),
    "no attestation": lambda r: r["fin"].update(attestation={"status": "unattested"}),
}
CODEX_DEFECTS = {
    "another model": lambda r: set_after(r["launch"]["argv"], "-m", "gpt-6-luna"),
    "not ephemeral": lambda r: r["launch"]["argv"].remove("--ephemeral"),
    "web search on": lambda r: r["launch"]["argv"].remove('web_search="disabled"'),
    "lower effort": lambda r: r["launch"]["argv"].__setitem__(r["launch"]["argv"].index("model_reasoning_effort=ultra"), "model_reasoning_effort=high"),
    "a writable sandbox": lambda r: set_after(r["launch"]["argv"], "--sandbox", "workspace-write"),
    "another folder": lambda r: r["launch"].update(cwd="/MOCK/elsewhere"),
    "a command": lambda r: r["events"].insert(3, {"type": "item.completed", "item": {"type": "command_execution"}}),
    "a started web search": lambda r: r["events"].insert(3, {"type": "item.started", "item": {"type": "web_search"}}),
    "a failed turn": lambda r: r["events"].append({"type": "turn.failed"}),
    "no message": lambda r: r["events"].pop(3),
    "two threads": lambda r: r["events"].insert(0, {"type": "thread.started"}),
    "a bad outcome": lambda r: r["fin"].update(outcome={"cls": "error"}),
}


@pytest.mark.parametrize("kind, record", [("claude", claude_record), ("codex", codex_record)])
def test_a_clean_record_passes(kind, record):
    out = run(kind, record())
    assert out["passed"], out["problems"]
    assert out["final"] == FINAL and out["tool_calls"] == 0
    assert out["attested"] == (kind == "claude")


@pytest.mark.parametrize("name", CLAUDE_DEFECTS)
def test_each_claude_defect_fails(name):
    rec = claude_record()
    CLAUDE_DEFECTS[name](rec)
    assert not run("claude", rec)["passed"]


@pytest.mark.parametrize("name", CODEX_DEFECTS)
def test_each_codex_defect_fails(name):
    rec = codex_record()
    CODEX_DEFECTS[name](rec)
    assert not run("codex", rec)["passed"]


@settings(max_examples=60, deadline=None)
@given(st.sets(st.sampled_from(sorted(CLAUDE_DEFECTS)), min_size=1))
def test_any_set_of_defects_fails(names):
    rec = claude_record()
    for n in sorted(names):
        CLAUDE_DEFECTS[n](rec)
    assert not run("claude", rec)["passed"]


def test_a_line_separator_inside_a_string_keeps_its_event():
    events = audit.events(json.dumps({"type": "x", "text": "a b\u0085c"}) + "\n" + "not json\n" + "[1, 2]\n")
    assert events == [{"type": "x", "text": "a b\u0085c"}]


def test_the_sent_prompt_must_match_the_registered_one():
    reg = "<!-- subfleet:headless -->\nMOCK registered prompt\n"
    exact = audit.sent_prompt(reg, reg)
    assert exact["ok"] and exact["lead_chars"] == 0 and exact["lead_sha256"] is None
    assert audit.sent_prompt(reg.rstrip("\n"), reg)["ok"]
    led = audit.sent_prompt("MOCK headless note\n\n" + reg, reg)
    assert not led["ok"] and led["lead_chars"] == len("MOCK headless note\n\n") and led["lead_sha256"]
    assert not audit.sent_prompt(reg + "MOCK extra", reg)["ok"]


@pytest.mark.parametrize("text", ["none", "None.", '"none"', "  NONE ", "nothing.", "n/a", "N/A", "(none)"])
def test_none_needs_no_reading(text):
    assert not audit.prior_flag(text)


@pytest.mark.parametrize("text", ["", "I recall the 2026 polls.", "The folder note says quillwort-1110", "nonetheless I know...",
                                  "None, though I recall the result.", "NONE beyond the brief", "N/A: no prior", "none.\nBut the polls..."])
def test_anything_else_needs_the_reading(text):
    assert audit.prior_flag(text)


def test_equal_texts_share_a_key_and_the_canary_is_found_in_any_case():
    assert audit.prior_key(" same ") == audit.prior_key("same")
    assert audit.prior_key("a") != audit.prior_key("b")
    assert audit.has_canary("... QUILLWORT-1110 ...", "quillwort-1110")
    assert not audit.has_canary("", "quillwort-1110")


def drop_config(argv, value):
    """Remove one `-c value` pair, or one bare flag."""
    i = argv.index(value)
    if i and argv[i - 1] == "-c":
        del argv[i - 1 : i + 1]
    else:
        del argv[i]


# Each rule the README lists for a launch or a stream: a change that breaks it, the problem it must
# raise, and how many problems that change raises in all.
CLAUDE_RULES = {
    "an inline hook setting": (lambda r: set_after(r["launch"]["argv"], "--settings", '{"env":{},"hooks":{"MOCK":[]}}'), "--settings holds more than environment variables", 1),
    "an inline setting whose variable holds an object": (lambda r: set_after(r["launch"]["argv"], "--settings", '{"env":{"MOCK":{"a":1}}}'), "--settings holds more than environment variables", 1),
    "an unreadable inline setting": (lambda r: set_after(r["launch"]["argv"], "--settings", "MOCK not json"), "--settings holds more than environment variables", 1),
    "two inline settings": (lambda r: r["launch"]["argv"].extend(["--settings", '{"env":{}}']), "--settings appears 2 times", 1),
    "an added system prompt": (lambda r: r["launch"]["argv"].extend(["--append-system-prompt", "MOCK"]), "2 argument(s) the audit does not know", 1),
    "a replaced system prompt": (lambda r: r["launch"]["argv"].extend(["--system-prompt", "MOCK"]), "2 argument(s) the audit does not know", 1),
    "a system prompt from a file": (lambda r: r["launch"]["argv"].extend(["--append-system-prompt-file=/MOCK/x"]), "2 argument(s) the audit does not know", 1),
    "a flag the audit has never seen": (lambda r: r["launch"]["argv"].append("--MOCK-new-flag"), "1 argument(s) the audit does not know", 1),
    "a second model flag": (lambda r: r["launch"]["argv"].extend(["--model", "MOCK"]), "--model appears 2 times", 1),
    "a second model flag, spelled with =": (lambda r: r["launch"]["argv"].append("--model=MOCK"), "--model appears 2 times", 1),
    "a second tools flag": (lambda r: r["launch"]["argv"].extend(["--tools", "Bash"]), "--tools appears 2 times", 1),
    "a second setting source": (lambda r: r["launch"]["argv"].extend(["--setting-sources", "user"]), "--setting-sources appears 2 times", 1),
    "a second permission mode": (lambda r: r["launch"]["argv"].extend(["--permission-mode", "default"]), "--permission-mode appears 2 times", 1),
    "allowed tools beyond the three": (lambda r: set_after(r["launch"]["argv"], "--allowedTools", "Read,Bash"), "allowed tools go beyond", 1),
    "an MCP server in the config": (lambda r: set_after(r["launch"]["argv"], "--mcp-config", '{"mcpServers":{"MOCK":{}}}'), "--mcp-config names a server", 1),
    "a second folder": (lambda r: set_after(r["launch"]["argv"], "--add-dir", "/MOCK/elsewhere"), "--add-dir names a folder other than the sandbox", 1),
    "no strict MCP config": (lambda r: r["launch"]["argv"].remove("--strict-mcp-config"), "--strict-mcp-config missing", 1),
    "slash commands on": (lambda r: r["launch"]["argv"].remove("--disable-slash-commands"), "--disable-slash-commands missing", 1),
    "a message that names no model": (lambda r: r["events"].insert(-1, {"type": "assistant", "message": {"content": []}}), "no model named", 1),
    "an assistant event with no message": (lambda r: r["events"].insert(-1, {"type": "assistant"}), "no model named", 1),
}
# The eight Codex flags the README lists, written out here so that dropping one from the audit fails a test.
CODEX_REQUIRED = ("--ephemeral", "--ignore-user-config", "--ignore-rules", "project_doc_max_bytes=0", "features.multi_agent=false",
                  "features.multi_agent_v2=false", "features.memories=false", 'web_search="disabled"')  # fmt: skip
CODEX_RULES = {
    **{f"without {flag}": ((lambda r, flag=flag: drop_config(r["launch"]["argv"], flag)), f"{flag} missing", 1) for flag in CODEX_REQUIRED},
    "a setting given twice": (lambda r: r["launch"]["argv"].extend(["-c", 'web_search="disabled"']), "1 configuration key(s) set more than once", 1),
    "a later lower effort": (lambda r: r["launch"]["argv"].extend(["-c", "model_reasoning_effort=low"]), "1 configuration key(s) set more than once", 2),
    "a feature switched on": (lambda r: r["launch"]["argv"].extend(["-c", "features.MOCK=true"]), "1 setting(s) beyond a feature switched off", 1),
    "a setting the audit has never seen": (lambda r: r["launch"]["argv"].extend(["-c", "MOCK_key=1"]), "1 setting(s) beyond a feature switched off", 1),
    "the long spelling of a setting": (lambda r: r["launch"]["argv"].extend(["--config", 'web_search="live"']), "2 argument(s) the audit does not know", 1),
    "a flag the audit has never seen": (lambda r: r["launch"]["argv"].append("--MOCK-new-flag"), "1 argument(s) the audit does not know", 1),
    "a second model": (lambda r: r["launch"]["argv"].extend(["-m", "MOCK"]), "-m appears 2 times", 1),
    "a second sandbox": (lambda r: r["launch"]["argv"].extend(["--sandbox", "workspace-write"]), "--sandbox appears 2 times", 1),
    "a second sandbox, spelled with =": (lambda r: r["launch"]["argv"].append("--sandbox=workspace-write"), "--sandbox appears 2 times", 1),
    "two turns": (lambda r: r["events"].extend([{"type": "turn.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "MOCK"}},
                                                 {"type": "turn.completed"}]), "turns: 2 started, 2 completed", 1),  # fmt: skip
    "a command": (lambda r: r["events"].insert(3, {"type": "item.completed", "item": {"type": "command_execution", "command": "cat /MOCK/lane-home/x"}}),
                  "1 kind(s) of item beyond messages, reasoning and to-do notes", 1),  # fmt: skip
}


def test_the_audit_requires_every_codex_flag_the_readme_lists():
    assert set(CODEX_REQUIRED) == set(audit.CODEX_FLAGS)


@pytest.mark.parametrize("name", CLAUDE_RULES)
def test_each_claude_rule_raises_its_own_problem(name):
    rec = claude_record()
    mutate, problem, count = CLAUDE_RULES[name]
    mutate(rec)
    out = run("claude", rec)
    assert [p for p in out["problems"] if problem in p] and len(out["problems"]) == count, out["problems"]


@pytest.mark.parametrize("name", CODEX_RULES)
def test_each_codex_rule_raises_its_own_problem(name):
    rec = codex_record()
    mutate, problem, count = CODEX_RULES[name]
    mutate(rec)
    out = run("codex", rec)
    assert [p for p in out["problems"] if problem in p] and len(out["problems"]) == count, out["problems"]


def test_no_problem_names_a_folder_a_tool_or_a_server():
    """Problems go to the public tables. A lane's paths, tool names and MCP server names stay private."""
    records = []
    for defects, record, kind in ((CLAUDE_DEFECTS, claude_record, "claude"), (CODEX_DEFECTS, codex_record, "codex")):
        for mutate in defects.values():
            rec = record()
            mutate(rec)
            records.append((kind, rec))
    for rules, record, kind in ((CLAUDE_RULES, claude_record, "claude"), (CODEX_RULES, codex_record, "codex")):
        for mutate, _, _ in rules.values():
            rec = record()
            mutate(rec)
            records.append((kind, rec))
    rec = claude_record()
    of_type(rec["events"], "assistant")["message"]["content"].append({"type": "tool_use", "name": "mcp__MOCKserver__MOCKtool"})
    of_type(rec["events"], "system", "init").update(tools=["Read", "mcp__MOCKserver__MOCKtool"], cwd="/MOCK/lane-home/work",
                                                    mcp_servers=[{"name": "MOCKserver"}])  # fmt: skip
    rec["launch"].update(cwd="/MOCK/lane-home/work")
    set_after(rec["launch"]["argv"], "--tools", "Read,MOCKtool")
    records.append(("claude", rec))
    rec = codex_record()
    rec["launch"].update(cwd="/MOCK/lane-home/work")
    rec["events"].insert(3, {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "MOCKserver", "tool": "MOCKtool"}})
    records.append(("codex", rec))
    seen = 0
    for kind, rec in records:
        for problem in run(kind, rec)["problems"]:
            seen += 1
            for private in ("/MOCK", "lane-home", "mcp__", "mcp_tool_call", "command_execution", "MOCKserver", "MOCKtool", "Bash"):
                assert private not in problem, problem
    assert seen > len(records) - 2


@pytest.mark.parametrize("text, found", [
    ("MOCK quillwort-1110", True), ("MOCK Quillwort 1110", True), ("MOCK quillwort\u20111110", True),
    ("MOCK QUILLWORT", True), ("MOCK quill wort", False), ("MOCK none", False), ("", False),
])  # fmt: skip
def test_the_code_word_counts_however_its_number_is_spelled(text, found):
    assert audit.has_canary(text, "quillwort-1110") is found
