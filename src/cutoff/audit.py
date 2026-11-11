"""The audit each context must pass before its answer counts.

A closed context is a Subfleet isolated run in an empty folder. The audit reads what Subfleet kept
for the attempt (the launch record, the provider's event stream, the finalization record and the
prompt as sent) and checks, by family:

- **Opus** (Claude Code): the launch pins `claude-opus-5-5`, offers only the three file-reading tools
  in plan mode, and loads no settings, memory or MCP server; the stream's one init event agrees; every
  assistant message names that model; the result's usage lists that model only; Subfleet attests it.
- **Sol** (Codex): the launch pins `gpt-6.1-sol` at ultra effort in an ephemeral, read-only session
  with user config, rules, project instructions, web search and multi-agent mode off; the stream holds
  one turn, started and completed. An isolated ephemeral Codex session leaves no served-model record
  that Subfleet can attest, so the pin in the launch record is the evidence; the audit records the
  model the answer names.
- **Both:** the context called no tool; the prompt it received ends with its registered prompt, byte
  for byte; and its working folder is the sandbox.

Separately, `prior_flag` marks an answer whose `forecaster.prior_context` says more than "none",
for the blinded reading the README describes, and `has_canary` reports whether the answer carries the
sandbox's code word.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

CLAUDE_MODEL = "claude-opus-5-5"
CODEX_MODEL = "gpt-6.1-sol"
CODEX_EFFORT = "ultra"
CLAUDE_TOOLS = {"Read", "Glob", "Grep"}
# What a Codex stream may hold besides its turn events: the model's messages and reasoning, and its own
# to-do notes. Anything else (a command, a file change, a web search, an MCP call, an error) fails.
CODEX_ITEMS = {"agent_message", "reasoning", "todo_list"}
CODEX_FLAGS = (
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "project_doc_max_bytes=0",
    "features.multi_agent=false",
    "features.multi_agent_v2=false",
    "features.memories=false",
    'web_search="disabled"',
)
# Only a bare "none" (or "nothing", "n/a"), with nothing but punctuation and space around it, skips the
# reading: "None, though I recall the result" goes to the reader.
_NONE = re.compile(r"^\W*(?:none|nothing|n/?a)\W*$", re.I)


def events(stream: str) -> list[dict]:
    """The JSON objects in an event stream, one per line. Lines end at a newline only: a JSON string
    may hold U+2028 or U+0085 raw, which `str.splitlines` would split on."""
    out = []
    for raw in stream.split("\n"):
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _after(argv: list, flag: str):
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def _same_folder(a, b) -> bool:
    return bool(a) and bool(b) and os.path.realpath(str(a)) == os.path.realpath(str(b))


def sent_prompt(sent: str, registered: str) -> dict:
    """Whether the prompt as sent matches the registered prompt, and what, if anything, came before it.

    Every registered prompt opens with Subfleet's headless marker, so Subfleet adds no note of its own
    and the two must match. `lead_chars` and `lead_sha256` record any text ahead of a prompt that
    otherwise ends with the registered one, which fails the check."""
    s, r = sent.rstrip("\n"), registered.rstrip("\n")
    ends = s.endswith(r)
    lead = s[: len(s) - len(r)] if ends else ""
    return {
        "ok": s == r,
        "lead_chars": len(lead),
        "lead_sha256": hashlib.sha256(lead.encode()).hexdigest() if ends and lead else None,
    }


def claude(stream: str, launch: dict, finalization: dict | None, sandbox) -> dict:
    problems: list[str] = []
    evs = events(stream)
    argv = launch.get("argv") or []
    if _after(argv, "--model") != CLAUDE_MODEL:
        problems.append(f"launch: model {_after(argv, '--model')!r}, not {CLAUDE_MODEL}")
    tools = set((_after(argv, "--tools") or "").split(","))
    if not tools <= CLAUDE_TOOLS:
        problems.append(f"launch: tools {sorted(tools)} go beyond {sorted(CLAUDE_TOOLS)}")
    if _after(argv, "--setting-sources") != "":
        problems.append("launch: setting sources are not empty")
    for flag in ("--safe-mode", "--strict-mcp-config", "--disable-slash-commands"):
        if flag not in argv:
            problems.append(f"launch: {flag} missing")
    if _after(argv, "--permission-mode") != "plan":
        problems.append("launch: not in plan mode")
    if not _same_folder(launch.get("cwd"), sandbox):
        problems.append(f"launch: working folder {launch.get('cwd')!r} is not the sandbox")
    inits = [e for e in evs if e.get("type") == "system" and e.get("subtype") == "init"]
    if len(inits) != 1:
        problems.append(f"stream: {len(inits)} init events")
    else:
        init = inits[0]
        if init.get("model") != CLAUDE_MODEL:
            problems.append(f"stream: init names model {init.get('model')!r}")
        if not set(init.get("tools") or []) <= CLAUDE_TOOLS:
            problems.append(f"stream: init lists tools {init.get('tools')}")
        if init.get("mcp_servers"):
            servers = init.get("mcp_servers")
            count = len(servers) if isinstance(servers, (list, dict)) else 1
            problems.append(f"stream: init lists {count} MCP server(s)")  # names stay in the private stream
        if not _same_folder(init.get("cwd"), sandbox):
            problems.append(f"stream: init working folder {init.get('cwd')!r} is not the sandbox")
    models, calls = set(), []
    for e in evs:
        msg = e.get("message")
        if e.get("type") == "assistant" and isinstance(msg, dict):
            if msg.get("model"):
                models.add(msg["model"])
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append(str(block.get("name")))
    if models != {CLAUDE_MODEL}:
        problems.append(f"stream: assistant messages name models {sorted(models)}")
    if calls:
        problems.append(f"the context called tools: {calls}")
    results = [e for e in evs if e.get("type") == "result"]
    final = ""
    if len(results) != 1 or results[0].get("subtype") != "success" or results[0].get("is_error"):
        problems.append(f"stream: {len(results)} result events, or the result is not a success")
    else:
        final = results[0].get("result") if isinstance(results[0].get("result"), str) else ""
        usage = set((results[0].get("modelUsage") or {}).keys())
        if usage != {CLAUDE_MODEL}:
            problems.append(f"stream: usage lists models {sorted(usage)}")
    att = (finalization or {}).get("attestation") or {}
    if att.get("status") != "attested" or att.get("served_model") != CLAUDE_MODEL:
        problems.append(f"finalization: attestation {att.get('status')!r} for model {att.get('served_model')!r}")
    return {
        "family": "opus",
        "passed": not problems,
        "problems": problems,
        "tool_calls": len(calls),
        "model_served": sorted(models)[0] if len(models) == 1 else None,
        "attested": att.get("status") == "attested",
        "final": final,
    }


def codex_final(evs: list[dict]) -> tuple[str, str | None]:
    """The final message of a `codex exec --json` stream, and why its turn did not finish cleanly (None
    when it did): one turn, started and completed, none failed, the completion last among the turn
    events, and a completed agent message with text; the final message is the last such."""
    started = completed = failed = 0
    last_turn, final = None, ""
    for e in evs:
        kind = e.get("type")
        if kind in ("turn.started", "turn.completed", "turn.failed"):
            started += kind == "turn.started"
            completed += kind == "turn.completed"
            failed += kind == "turn.failed"
            last_turn = kind
        elif kind == "item.completed":
            item = e.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final = item["text"]
    if started != 1 or completed != 1 or failed or last_turn != "turn.completed":
        return final, f"turns: {started} started, {completed} completed, {failed} failed, last {last_turn}"
    if not final.strip():
        return final, "no completed agent message with text"
    return final, None


def codex(stream: str, launch: dict, finalization: dict | None, sandbox) -> dict:
    problems: list[str] = []
    evs = events(stream)
    argv = launch.get("argv") or []
    if _after(argv, "-m") != CODEX_MODEL:
        problems.append(f"launch: model {_after(argv, '-m')!r}, not {CODEX_MODEL}")
    for flag in CODEX_FLAGS:
        if flag not in argv:
            problems.append(f"launch: {flag} missing")
    if f"model_reasoning_effort={CODEX_EFFORT}" not in argv:
        problems.append(f"launch: effort is not {CODEX_EFFORT}")
    if _after(argv, "--sandbox") != "read-only":
        problems.append("launch: the sandbox is not read-only")
    if not _same_folder(launch.get("cwd"), sandbox):
        problems.append(f"launch: working folder {launch.get('cwd')!r} is not the sandbox")
    if sum(e.get("type") == "thread.started" for e in evs) != 1:
        problems.append("stream: not exactly one thread")
    calls = [
        str(e["item"].get("type"))
        for e in evs
        if e.get("type") == "item.completed" and isinstance(e.get("item"), dict)
        and e["item"].get("type") not in CODEX_ITEMS
    ]
    started = {
        str(e["item"].get("type"))
        for e in evs
        if e.get("type") == "item.started" and isinstance(e.get("item"), dict)
    } - CODEX_ITEMS
    other = sorted(set(calls) | started)
    if other:
        problems.append(f"the context called tools or raised errors: {other}")
    final, why = codex_final(evs)
    if why:
        problems.append(f"stream: {why}")
    outcome = (finalization or {}).get("outcome") or {}
    if outcome.get("cls") != "ok":
        problems.append(f"finalization: outcome {outcome.get('cls')!r}")
    att = (finalization or {}).get("attestation") or {}
    return {
        "family": "sol",
        "passed": not problems,
        "problems": problems,
        "tool_calls": max(len(calls), len(started)),
        "model_served": att.get("served_model"),
        "attested": att.get("status") == "attested",
        "final": final,
    }


def prior_flag(prior_context: str) -> bool:
    """Whether a `prior_context` needs the blinded reading: it does unless it says only "none"."""
    return not _NONE.match(prior_context or "")


def prior_key(prior_context: str) -> str:
    """The key a reading decision is filed under: the text's SHA-256, so equal texts share a decision
    and the reader never sees which context or arm a text came from."""
    return hashlib.sha256((prior_context or "").strip().encode()).hexdigest()


def has_canary(text: str, word: str) -> bool:
    return word.lower() in (text or "").lower()
