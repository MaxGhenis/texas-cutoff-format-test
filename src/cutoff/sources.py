"""The sixteen sealed Texas runs whose research becomes the evidence files, and the check that each
source file still matches the hash its run's sealed manifest gave it on 2026-11-03."""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import paths

OPUS = tuple(f"opus-{i}" for i in range(1, 11))
SOL = tuple(f"sol-{i}" for i in range(1, 7))
LABELS = OPUS + SOL
# The runs whose answers the paper accepted. Only these have a sealed jump for the bridge; opus-2, 5, 6
# and 7 failed the answer check, but their research stands.
ACCEPTED = ("opus-1", "opus-3", "opus-4", "opus-8", "opus-9", "opus-10") + SOL

# Both manifests sit in the public Texas repository, stamped on 2026-11-03. The second lists the hashes
# of the Sol runs' session logs, which stay out of that repository.
OPUS_MANIFEST = "prereg/2026-11-03-collected/SHA256SUMS"
SOL_MANIFEST = "prereg/2026-11-03-codex-sessions/SHA256SUMS"


class SourceError(RuntimeError):
    pass


def family(label: str) -> str:
    return label.split("-")[0]


def _manifest(root: Path, rel: str) -> dict[str, str]:
    out = {}
    for line in (root / rel).read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip()] = digest
    return out


def source_files(label: str) -> tuple[Path, list[Path]]:
    """The repository root and the sealed files a run's evidence comes from."""
    if family(label) == "opus":
        root = paths.PUBLIC_TEXAS
        return root, [root / "runs" / label / "transcript.jsonl"]
    root = paths.PRIVATE_TEXAS
    return root, sorted((root / "runs" / label / "codex-sessions").glob("rollout-*.jsonl"))


def verified_sources(label: str) -> list[dict]:
    """Each source file with its SHA-256, after checking it against the sealed manifest."""
    root, files = source_files(label)
    manifest = _manifest(paths.PUBLIC_TEXAS, OPUS_MANIFEST if family(label) == "opus" else SOL_MANIFEST)
    expected = {k for k in manifest if k.startswith(f"runs/{label}/")}
    expected = {k for k in expected if k.endswith("transcript.jsonl")} if family(label) == "opus" else {
        k for k in expected if "/codex-sessions/rollout-" in k
    }
    rels = {str(f.relative_to(root)) for f in files}
    if not files or rels != expected:
        raise SourceError(f"{label}: source files {sorted(rels)} differ from the sealed manifest's {sorted(expected)}")
    out = []
    for f in files:
        rel = str(f.relative_to(root))
        if not f.is_file():
            raise SourceError(f"{label}: {rel} is missing")
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        if digest != manifest[rel]:
            raise SourceError(f"{label}: {rel} has SHA-256 {digest}, the sealed manifest {manifest[rel]}")
        out.append({"path": rel, "sha256": digest})
    return out
