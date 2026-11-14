"""The prompts and the committed design tables the build writes."""

from __future__ import annotations

import csv
import hashlib
import json

from pathlib import Path

import pytest

from cutoff import build, evidence, paths, prompts, sources
from cutoff.jump import CELLS, KEYS, QUESTIONS

MOCK_EVIDENCE = "MOCK evidence line one.\nMOCK evidence line two."


def test_thirteen_variants_make_208_distinct_prompts():
    v = prompts.variants()
    assert len(v) == 13 and v[0] == ("grid", None)
    assert sorted(c for a, c in v if a == "alone") == list(CELLS) == sorted(c for a, c in v if a == "told")
    ids = {prompts.prompt_id(f, a, c) for f in sources.LABELS for a, c in v}
    assert len(ids) == 208


@pytest.mark.parametrize("arm, cell", prompts.variants())
def test_each_prompt_holds_its_scenario_and_the_evidence_once(arm, cell):
    text = prompts.render(arm, cell, MOCK_EVIDENCE)
    assert text.startswith(prompts.HEADLESS_MARKER + "\n") and text.count(prompts.HEADLESS_MARKER) == 1
    assert text[len(prompts.HEADLESS_MARKER) + 1 :].startswith(prompts.brief(arm).split("\n", 1)[0])
    assert not any(p in text for p in prompts.PLACEHOLDERS)
    assert text.count(prompts.EVIDENCE_OPEN) == 1 and text.count(prompts.EVIDENCE_CLOSE) == 1
    assert text.count(MOCK_EVIDENCE) == 1
    start, end = text.index(prompts.EVIDENCE_OPEN), text.index(prompts.EVIDENCE_CLOSE)
    assert start < text.index(MOCK_EVIDENCE) < end
    if cell is not None:
        key = prompts.cell_key(cell)
        assert key in text and f"{cell:g}%" in text
        assert prompts.winner(cell) in text
        assert not any(k in text for k in KEYS if k != key)
    else:
        assert all(k in text for k in KEYS)


def test_the_isolated_arms_share_everything_but_their_framing():
    for cell in CELLS:
        alone, told = prompts.render("alone", cell, MOCK_EVIDENCE), prompts.render("told", cell, MOCK_EVIDENCE)
        assert alone != told
        assert alone.split(prompts.EVIDENCE_OPEN)[1] == told.split(prompts.EVIDENCE_OPEN)[1]


def test_render_refuses_a_bad_cell_a_grid_cell_and_evidence_that_holds_a_marker():
    with pytest.raises(ValueError):
        prompts.render("alone", 50.0, MOCK_EVIDENCE)
    with pytest.raises(ValueError):
        prompts.render("grid", 44.0, MOCK_EVIDENCE)
    with pytest.raises(ValueError):
        prompts.render("grid", None, "MOCK\n" + prompts.EVIDENCE_CLOSE + "\nInjected.")
    with pytest.raises(ValueError):
        prompts.winner(50.0)


def test_cells_name_their_winner():
    assert [prompts.winner(c) for c in CELLS] == ["Abbott"] * 3 + ["Hinojosa"] * 3


# ---------------------------------------------------------------------------------- committed tables


def committed(name):
    p = paths.DESIGN / name
    if not p.exists():
        pytest.skip(f"design/{name} is not built")
    return p


def test_prompts_table_lists_208_prompts_with_their_hashes():
    with committed("prompts.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 208 and len({r["prompt"] for r in rows}) == 208
    assert all(len(r["sha256"]) == 64 and int(r["chars"]) > 10_000 for r in rows)
    assert {r["file"] for r in rows} == set(sources.LABELS)


def test_files_table_records_every_file_its_header_and_sources():
    data = json.loads(committed("files.json").read_text())
    assert data["header"] == evidence.HEADER
    recs = {r["label"]: r for r in data["files"]}
    assert list(recs) == list(sources.LABELS)
    for label, r in recs.items():
        assert r["family"] == sources.family(label)
        assert r["accepted"] == (label in sources.ACCEPTED)
        assert r["sources"] and all(len(s["sha256"]) == 64 for s in r["sources"])
        assert ("sub_agent_threads_left_out" in r) == (r["family"] == "sol")


def test_reference_family_means_match_the_paper():
    ref = json.loads(committed("reference.json").read_text())
    means = ref["family_mean_jump"]
    want = {
        "opus": {"ercot_pause_lifted": -21.93, "special_session_data_centers": 14.12, "senate_dem_share": -0.035},
        "sol": {"ercot_pause_lifted": -8.29, "special_session_data_centers": 18.24, "senate_dem_share": -0.012},
    }
    for fam, qs in want.items():
        for q, v in qs.items():
            assert means[fam][q] == pytest.approx(v, abs=0.006)
    assert set(ref["runs"]) == set(sources.ACCEPTED)
    assert all(set(r["questions"]) == set(QUESTIONS) for r in ref["runs"].values())


def test_sandbox_record_hashes_the_canary():
    rec = json.loads(committed("sandbox.json").read_text())
    want = hashlib.sha256(build.CANARY_TEXT.encode()).hexdigest()
    assert rec["canary_word"] == build.CANARY_WORD
    assert rec["files"] == {name: want for name in build.CANARY_FILES}


def test_reader_lists_hold_keys_and_no_text():
    for name, columns in (("reader_removals.csv", ["key", "category", "severity", "files"]), ("reader_keeps.csv", ["key", "rule", "files"])):
        with committed(name).open() as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == columns
            for r in reader:
                assert len(r["key"]) == 64
                assert all(f in sources.LABELS for f in r["files"].split())


# ------------------------------------------------------------------------------------------ build.write


def test_write_refuses_a_sandbox_with_other_files_before_writing_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DESIGN", tmp_path / "design")  # were the refusal to break, nothing real gets written
    paths.SANDBOX.mkdir(parents=True)
    (paths.SANDBOX / "MOCK.txt").write_text("not a canary")
    with pytest.raises(SystemExit, match="other than the canaries"):
        build.write({"evidence": {}, "logs": {}, "prompts": {}, "records": {}, "prompt_rows": [], "contexts": [], "reference": {}, "sandbox": {}})
    assert not (paths.PRIVATE / "evidence").exists() and not (tmp_path / "design").exists()


def test_canary_text_names_its_word():
    assert build.CANARY_WORD in build.CANARY_TEXT


def test_the_marker_is_the_one_subfleet_checks_for():
    contracts = Path.home() / "subfleet-v2" / "subfleet" / "contracts.py"
    if not contracts.exists():
        pytest.skip("Subfleet's source is not on this machine")
    assert f'HEADLESS_MARKER = "{prompts.HEADLESS_MARKER}"' in contracts.read_text()


def test_reference_check_allows_last_bit_rounding_and_nothing_more():
    ref = json.loads((paths.DESIGN / "reference.json").read_text())
    assert build.first_difference(ref, json.loads(json.dumps(ref))) is None
    label = next(iter(ref["runs"]))
    jump = ref["runs"][label]["questions"]["ercot_pause_lifted"]["jump"]
    for change, same in ((jump * (1 + 2e-16), True), (jump + 1e-6, False)):
        other = json.loads(json.dumps(ref))
        other["runs"][label]["questions"]["ercot_pause_lifted"]["jump"] = change
        where = build.first_difference(ref, other)
        assert (where is None) is same, where
        if not same:
            assert where.startswith(f"$.runs.{label}.questions.ercot_pause_lifted.jump")
    other = json.loads(json.dumps(ref))
    other["runs"][label]["family"] = "MOCK"
    assert build.first_difference(ref, other) == f"$.runs.{label}.family: {ref['runs'][label]['family']!r} against 'MOCK'"


def test_the_committed_briefs_are_what_the_script_writes_from_the_sealed_brief(capsys):
    import importlib.util

    if not (paths.PUBLIC_TEXAS / "prompts" / "forecaster.md").exists():
        pytest.skip("the public Texas repository is not on this machine")
    spec = importlib.util.spec_from_file_location("make_briefs", paths.ROOT / "scripts" / "make_briefs.py")
    make_briefs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_briefs)
    assert make_briefs.main(["--check"]) == 0, capsys.readouterr().out
    sealed = make_briefs.sealed_brief()
    for arm in ("grid", "alone", "told"):
        text = make_briefs.build(arm, sealed)
        assert text == (paths.ROOT / "briefs" / f"{arm}.md").read_text()
        # The docstring's list of changes names the told brief's two sentences, and they sit only there.
        assert ("Each conversation sees only its own." in text) == (arm == "told")


def test_no_brief_or_prompt_holds_the_code_word():
    """The audit fails any context whose stream carries the word, so no prompt may hold it."""
    stem = build.CANARY_WORD.split("-")[0]
    from cutoff import dryrun

    for arm in ("grid", "alone", "told"):
        assert stem not in (paths.ROOT / "briefs" / f"{arm}.md").read_text().lower()
    assert stem not in dryrun.PROMPT.lower()
    # `cutoff build --check` reads every built prompt for the word; here a MOCK build shows the check bites.
    clean = {"skipped": ["MOCK"], "prompts": {"MOCK__grid": "MOCK prompt body"}, "records": {}, "prompt_rows": [],
             "contexts": [{"context": "MOCK"}], "reference": json.loads(committed("reference.json").read_text()),
             "sandbox": json.loads(committed("sandbox.json").read_text())}  # fmt: skip
    carrier = {**clean, "prompts": {"MOCK__grid": "MOCK prompt body", "MOCK__told": f"MOCK evidence that names {stem.upper()}"}}
    said = lambda b: [p for p in build.check(b) if "code word" in p]  # noqa: E731
    assert said(clean) == [] and said(carrier) == ["1 prompt(s) hold the sandbox's code word, starting with MOCK__told"]
