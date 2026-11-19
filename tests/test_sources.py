"""Tests for cutoff.sources: the sixteen sealed runs and the check of their files against the manifests.

Every file these tests write is MOCK data in a temporary folder. The tests at the end read the real
sealed repositories through cutoff.paths and skip when a repository is not on the machine; they assert
on paths, hashes and counts only.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cutoff import design, paths, sources

# Property tests run the same examples every time and keep no example database in the repository.
PROPERTY = settings(max_examples=60, deadline=None, derandomize=True, database=None)

HEX64 = re.compile(r"[0-9a-f]{64}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------------------------- MOCK repositories


def put(root: Path, rel: str, data: bytes) -> str:
    """Write MOCK bytes at root/rel and return the manifest line that seals them."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"{digest(data)}  {rel}"


def seal(root: Path, manifest: str, lines: list[str]) -> None:
    path = root / manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def mock_public(root: Path, labels=("opus-1",)) -> dict[str, bytes]:
    """A MOCK public Texas repository: each run has a transcript and two files the check ignores."""
    lines, transcripts = [], {}
    for label in labels:
        transcripts[label] = f'{{"MOCK": "transcript of {label}"}}\n'.encode()
        lines.append(put(root, f"runs/{label}/transcript.jsonl", transcripts[label]))
        lines.append(put(root, f"runs/{label}/meta.json", b'{"MOCK": true}\n'))
        lines.append(put(root, f"runs/{label}/response.md", f"MOCK answer of {label}\n".encode()))
    lines.append(put(root, "graph/graph.yaml", b"MOCK: graph\n"))
    seal(root, sources.OPUS_MANIFEST, lines)
    return transcripts


MOCK_ROLLOUTS = ("rollout-2026-11-03T13-10-04-aaaa.jsonl", "rollout-2026-11-03T13-12-00-bbbb.jsonl",
                 "rollout-2026-11-03T13-11-30-cccc.jsonl")  # fmt: skip


def mock_private(root: Path, label="sol-1", names=MOCK_ROLLOUTS) -> dict[str, bytes]:
    """A MOCK private Texas repository: one Sol run with session logs and files the check ignores. The
    manifest that seals the logs goes where the real one sits: in the public repository."""
    lines, logs = [], {}
    for name in names:
        logs[name] = f'{{"MOCK": "session log {name}"}}\n'.encode()
        lines.append(put(root, f"runs/{label}/codex-sessions/{name}", logs[name]))
    lines.append(put(root, f"runs/{label}/meta.json", b'{"MOCK": true}\n'))
    lines.append(put(root, f"runs/{label}/transcript.jsonl", b'{"MOCK": "not a session log"}\n'))
    lines.append(put(root, f"outputs/{label}.json", b'{"MOCK": true}\n'))
    seal(paths.PUBLIC_TEXAS, sources.SOL_MANIFEST, lines)
    return logs


@pytest.fixture
def mock_repos(tmp_path, monkeypatch):
    """Point cutoff.paths at two empty MOCK repositories and return their roots."""
    public, private = tmp_path / "public", tmp_path / "private"
    public.mkdir()
    private.mkdir()
    monkeypatch.setattr(paths, "PUBLIC_TEXAS", public)
    monkeypatch.setattr(paths, "PRIVATE_TEXAS", private)
    return public, private


def rewrite_manifest(root: Path, manifest: str, change) -> None:
    """Apply `change` to the list of manifest lines."""
    path = root / manifest
    path.write_text("\n".join(change(path.read_text().splitlines())) + "\n")


# ------------------------------------------------------------------------------------------------ labels


def test_labels_are_the_sixteen_sealed_runs():
    assert sources.OPUS == tuple(f"opus-{i}" for i in range(1, 11))
    assert sources.SOL == tuple(f"sol-{i}" for i in range(1, 7))
    assert sources.LABELS == sources.OPUS + sources.SOL
    assert len(sources.LABELS) == 16
    assert len(set(sources.LABELS)) == 16


def test_accepted_are_twelve_of_the_sixteen():
    assert len(sources.ACCEPTED) == 12
    assert len(set(sources.ACCEPTED)) == 12
    assert set(sources.ACCEPTED) <= set(sources.LABELS)
    # The module's comment: opus-2, 5, 6 and 7 failed the answer check; every Sol run passed.
    assert set(sources.LABELS) - set(sources.ACCEPTED) == {"opus-2", "opus-5", "opus-6", "opus-7"}
    assert set(sources.SOL) <= set(sources.ACCEPTED)


def test_accepted_keeps_the_order_of_labels():
    # build.py lists runs in LABELS order; ACCEPTED in the same order keeps the two tables aligned.
    assert list(sources.ACCEPTED) == [x for x in sources.LABELS if x in sources.ACCEPTED]


@pytest.mark.parametrize(
    "label, expected",
    [("opus-1", "opus"), ("opus-10", "opus"), ("sol-1", "sol"), ("sol-6", "sol")],
)
def test_family_examples(label, expected):
    assert sources.family(label) == expected


@PROPERTY
@given(st.sampled_from(("opus", "sol")), st.integers(min_value=0, max_value=10**9))
def test_family_is_the_text_before_the_hyphen(fam, n):
    assert sources.family(f"{fam}-{n}") == fam


def test_every_label_has_one_of_the_two_families():
    assert {sources.family(x) for x in sources.OPUS} == {"opus"}
    assert {sources.family(x) for x in sources.SOL} == {"sol"}


def test_each_design_family_has_an_accepted_run():
    # build.reference() averages the accepted runs of each design family, so none can be empty.
    assert {sources.family(x) for x in sources.ACCEPTED} == set(design.FAMILIES)


# ---------------------------------------------------------------------------------------------- manifest


def test_manifest_maps_each_name_to_its_digest(tmp_path):
    # MOCK digests. A blank line is skipped, and a name keeps its inner spaces.
    (tmp_path / "SUMS").write_text("aa11  runs/x/a.txt\n\nbb22  runs/x/b c.txt\n   \ncc33 runs/y/d.txt\n")
    assert sources._manifest(tmp_path, "SUMS") == {
        "runs/x/a.txt": "aa11",
        "runs/x/b c.txt": "bb22",
        "runs/y/d.txt": "cc33",
    }


MOCK_NAMES = st.lists(
    st.text(alphabet="abcXYZ019-_.", min_size=1, max_size=6), min_size=1, max_size=4
).map("/".join)


@PROPERTY
@given(st.dictionaries(MOCK_NAMES, st.binary(max_size=40), min_size=0, max_size=6))
def test_manifest_round_trip(files):
    """For any MOCK set of names: parsing "digest  name" lines gives back each name's digest."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "SUMS").write_text("".join(f"{digest(data)}  {name}\n" for name, data in files.items()))
        assert sources._manifest(root, "SUMS") == {name: digest(data) for name, data in files.items()}


# ------------------------------------------------------------------------------------------ source_files


def test_source_files_opus_is_the_transcript_in_the_public_repository(mock_repos):
    public, _ = mock_repos
    root, files = sources.source_files("opus-3")
    assert root == public
    assert files == [public / "runs" / "opus-3" / "transcript.jsonl"]


def test_source_files_sol_are_the_sorted_session_logs_in_the_private_repository(mock_repos):
    _, private = mock_repos
    mock_private(private)
    (private / "runs/sol-1/codex-sessions/notes.txt").write_text("MOCK: not a session log\n")
    root, files = sources.source_files("sol-1")
    assert root == private
    assert [f.name for f in files] == sorted(MOCK_ROLLOUTS)
    assert all(f.parent == private / "runs" / "sol-1" / "codex-sessions" for f in files)


def test_source_files_sol_is_empty_when_the_run_has_no_logs(mock_repos):
    assert sources.source_files("sol-2")[1] == []


# -------------------------------------------------------------------------------------- verified_sources


def test_verified_opus_source_is_the_transcript_with_its_hash(mock_repos):
    public, _ = mock_repos
    transcripts = mock_public(public)
    assert sources.verified_sources("opus-1") == [
        {"path": "runs/opus-1/transcript.jsonl", "sha256": digest(transcripts["opus-1"])}
    ]


def test_verified_sol_sources_are_the_session_logs_in_sorted_order(mock_repos):
    _, private = mock_repos
    logs = mock_private(private)
    assert sources.verified_sources("sol-1") == [
        {"path": f"runs/sol-1/codex-sessions/{name}", "sha256": digest(logs[name])} for name in sorted(logs)
    ]


def test_a_run_is_not_confused_with_one_whose_label_it_starts(mock_repos):
    # "runs/opus-1/" must not match "runs/opus-10/": each run sees only its own transcript.
    public, _ = mock_repos
    transcripts = mock_public(public, labels=("opus-1", "opus-10"))
    assert transcripts["opus-1"] != transcripts["opus-10"]
    for label in ("opus-1", "opus-10"):
        assert sources.verified_sources(label) == [
            {"path": f"runs/{label}/transcript.jsonl", "sha256": digest(transcripts[label])}
        ]


def test_opus_hash_mismatch_raises(mock_repos):
    public, _ = mock_repos
    mock_public(public)
    (public / "runs/opus-1/transcript.jsonl").write_bytes(b'{"MOCK": "edited after the seal"}\n')
    with pytest.raises(sources.SourceError):
        sources.verified_sources("opus-1")


def test_sol_hash_mismatch_in_any_log_raises(mock_repos):
    _, private = mock_repos
    mock_private(private)
    for name in MOCK_ROLLOUTS:
        path = private / "runs/sol-1/codex-sessions" / name
        sealed = path.read_bytes()
        path.write_bytes(sealed + b" ")
        with pytest.raises(sources.SourceError):
            sources.verified_sources("sol-1")
        path.write_bytes(sealed)
    assert len(sources.verified_sources("sol-1")) == len(MOCK_ROLLOUTS)  # restored, it passes again


def test_opus_transcript_absent_from_the_manifest_raises(mock_repos):
    public, _ = mock_repos
    mock_public(public)
    rewrite_manifest(public, sources.OPUS_MANIFEST, lambda ls: [x for x in ls if "transcript.jsonl" not in x])
    with pytest.raises(sources.SourceError):
        sources.verified_sources("opus-1")


def test_opus_run_absent_from_the_manifest_raises(mock_repos):
    # The manifest seals opus-1 only; opus-2 has a transcript on disk that no manifest line covers.
    public, _ = mock_repos
    mock_public(public)
    put(public, "runs/opus-2/transcript.jsonl", b'{"MOCK": "unsealed"}\n')
    with pytest.raises(sources.SourceError):
        sources.verified_sources("opus-2")


def test_sol_log_on_disk_but_not_in_the_manifest_raises(mock_repos):
    _, private = mock_repos
    mock_private(private)
    put(private, "runs/sol-1/codex-sessions/rollout-2026-11-03T14-00-00-dddd.jsonl", b'{"MOCK": "extra"}\n')
    with pytest.raises(sources.SourceError):
        sources.verified_sources("sol-1")


def test_sol_log_in_the_manifest_but_not_on_disk_raises(mock_repos):
    _, private = mock_repos
    mock_private(private)
    (private / "runs/sol-1/codex-sessions" / MOCK_ROLLOUTS[0]).unlink()
    with pytest.raises(sources.SourceError):
        sources.verified_sources("sol-1")


def test_sol_run_with_no_logs_raises(mock_repos):
    # sol-2 has no folder and no manifest line: an empty file set never verifies.
    _, private = mock_repos
    mock_private(private)
    with pytest.raises(sources.SourceError):
        sources.verified_sources("sol-2")


def test_other_sealed_files_of_a_run_need_not_exist(mock_repos):
    # The manifests also seal each run's answer and metadata; only the evidence sources are checked here.
    public, private = mock_repos
    mock_public(public)
    mock_private(private)
    (public / "runs/opus-1/meta.json").unlink()
    (private / "runs/sol-1/meta.json").unlink()
    assert len(sources.verified_sources("opus-1")) == 1
    assert len(sources.verified_sources("sol-1")) == len(MOCK_ROLLOUTS)


def test_missing_opus_transcript_raises_source_error(mock_repos):
    public, _ = mock_repos
    mock_public(public)
    (public / "runs/opus-1/transcript.jsonl").unlink()
    with pytest.raises(sources.SourceError):
        sources.verified_sources("opus-1")


def test_missing_opus_transcript_never_verifies(mock_repos):
    """Whatever the exception's type, a missing transcript does not come back as verified."""
    public, _ = mock_repos
    mock_public(public)
    (public / "runs/opus-1/transcript.jsonl").unlink()
    with pytest.raises((sources.SourceError, OSError)):
        sources.verified_sources("opus-1")


@PROPERTY
@given(st.binary(min_size=1, max_size=200), st.data())
def test_verified_hash_is_the_sha256_and_any_changed_byte_fails(content, data):
    """For any MOCK transcript bytes: the check returns their SHA-256, and it raises SourceError once
    any one byte differs from the sealed bytes."""
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        root = Path(tmp)
        mp.setattr(paths, "PUBLIC_TEXAS", root)
        seal(root, sources.OPUS_MANIFEST, [put(root, "runs/opus-4/transcript.jsonl", content)])
        assert sources.verified_sources("opus-4") == [
            {"path": "runs/opus-4/transcript.jsonl", "sha256": digest(content)}
        ]
        i = data.draw(st.integers(0, len(content) - 1))
        flip = data.draw(st.integers(1, 255))
        changed = content[:i] + bytes([content[i] ^ flip]) + content[i + 1 :]
        (root / "runs/opus-4/transcript.jsonl").write_bytes(changed)
        with pytest.raises(sources.SourceError):
            sources.verified_sources("opus-4")


@PROPERTY
@given(st.sets(st.sampled_from(MOCK_ROLLOUTS + ("rollout-9.jsonl", "rollout-a.jsonl")), max_size=5))
def test_sol_file_set_must_equal_the_manifest(on_disk):
    """For any set of MOCK session logs on disk: the check passes only when the set is the sealed one."""
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        root = Path(tmp)
        mp.setattr(paths, "PRIVATE_TEXAS", root)
        mp.setattr(paths, "PUBLIC_TEXAS", root)
        sealed = mock_private(root)
        folder = root / "runs/sol-1/codex-sessions"
        for name in sealed:
            if name not in on_disk:
                (folder / name).unlink()
        for name in on_disk - set(sealed):
            (folder / name).write_bytes(b'{"MOCK": "unsealed log"}\n')
        if on_disk == set(sealed):
            assert [x["path"].rsplit("/", 1)[1] for x in sources.verified_sources("sol-1")] == sorted(sealed)
        else:
            with pytest.raises(sources.SourceError):
                sources.verified_sources("sol-1")


# ------------------------------------------------------------------------- the real sealed repositories


def real_manifest(root: Path, rel: str) -> None:
    if not (root / rel).exists():
        pytest.skip("the sealed Texas repository this test reads is not on this machine")


@pytest.mark.parametrize("label", sources.OPUS)
def test_real_opus_sources_match_the_sealed_manifest(label):
    real_manifest(paths.PUBLIC_TEXAS, sources.OPUS_MANIFEST)
    if not (paths.PUBLIC_TEXAS / "runs" / label / "transcript.jsonl").exists():
        pytest.skip(f"the public Texas repository has no transcript for {label}")
    out = sources.verified_sources(label)
    assert [x["path"] for x in out] == [f"runs/{label}/transcript.jsonl"]
    assert all(HEX64.fullmatch(x["sha256"]) for x in out)


@pytest.mark.parametrize("label", sources.SOL)
def test_real_sol_sources_match_the_sealed_manifest(label):
    real_manifest(paths.PUBLIC_TEXAS, sources.SOL_MANIFEST)
    if not (paths.PRIVATE_TEXAS / "runs" / label / "codex-sessions").is_dir():
        pytest.skip("the private Texas repository is not on this machine")
    out = sources.verified_sources(label)
    assert len(out) >= 1
    assert [x["path"] for x in out] == sorted(x["path"] for x in out)
    assert all(x["path"].startswith(f"runs/{label}/codex-sessions/rollout-") for x in out)
    assert all(HEX64.fullmatch(x["sha256"]) for x in out)


@pytest.mark.parametrize("label", sources.LABELS)
def test_design_records_the_sources_the_manifest_seals(label):
    """design/files.json and the sealed manifest name the same source files with the same hashes."""
    table = paths.DESIGN / "files.json"
    if not table.exists():
        pytest.skip("design/files.json is not built")
    if sources.family(label) == "opus":
        real_manifest(paths.PUBLIC_TEXAS, sources.OPUS_MANIFEST)
    else:
        real_manifest(paths.PUBLIC_TEXAS, sources.SOL_MANIFEST)
        if not (paths.PRIVATE_TEXAS / "runs" / label / "codex-sessions").is_dir():
            pytest.skip("the private Texas repository is not on this machine")
    records = {r["label"]: r for r in json.loads(table.read_text())["files"]}
    if label not in records:
        pytest.skip(f"design/files.json has no record for {label}")
    assert records[label]["sources"] == sources.verified_sources(label)
    assert records[label]["family"] == sources.family(label)
    assert records[label]["accepted"] == (label in sources.ACCEPTED)
