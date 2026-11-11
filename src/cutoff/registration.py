"""The stamped registration and the checks against it.

`prereg/registration/SHA256SUMS` lists a SHA-256 for every registered file, and `SHA256SUMS.ots`
timestamps that list. Dispatch refuses to send a context while any stimulus file differs from the
list (`problems`). The analysis and the replicate rule run either way, but they list every registered
file that changed since the stamp, with the deviation records under `prereg/` that name it
(`changes`), so a changed rule can't run unseen.
"""

from __future__ import annotations

import hashlib

from . import paths

REGISTRATION = paths.ROOT / "prereg" / "registration"
# What a dispatch needs unchanged since the stamp: the stimulus and the tables that name it.
STIMULUS = ("briefs/grid.md", "briefs/alone.md", "briefs/told.md", "design/prompts.csv", "design/contexts.csv",
            "design/files.json", "design/sandbox.json")  # fmt: skip


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict[str, str]:
    out = {}
    for line in (REGISTRATION / "SHA256SUMS").read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip()] = digest
    return out


def _state(rel: str, digest: str) -> str | None:
    p = paths.ROOT / rel
    if not p.is_file():
        return "missing"
    return "changed" if sha(p) != digest else None


def problems(names=None) -> list[str]:
    """Why a dispatch may not run: no stamped list, or a stimulus file that differs from it."""
    names = STIMULUS if names is None else names
    if not (REGISTRATION / "SHA256SUMS").exists():
        return ["no registration: prereg/registration/SHA256SUMS is missing"]
    out = []
    if not (REGISTRATION / "SHA256SUMS.ots").exists():
        out.append("the registration has no OpenTimestamps stamp (SHA256SUMS.ots)")
    listed = manifest()
    for rel in names:
        if rel not in listed:
            out.append(f"{rel} is not in the registration")
        elif state := _state(rel, listed[rel]):
            out.append(f"{rel} {'is missing' if state == 'missing' else 'changed since the registration'}")
    return out


def deviation_records() -> list:
    """Dated deviation records: the Markdown files directly under prereg/."""
    folder = REGISTRATION.parent
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def changes() -> dict:
    """Every registered file that differs from the stamped list, with the deviation records naming it."""
    if not (REGISTRATION / "SHA256SUMS").exists():
        return {"registered": False, "stamped": False, "changed": []}
    records = [(p, p.read_text(errors="replace")) for p in deviation_records()]
    changed = []
    for rel, digest in sorted(manifest().items()):
        if state := _state(rel, digest):
            named_in = [f"prereg/{p.name}" for p, text in records if rel in text]
            changed.append({"file": rel, "state": state, "deviations": named_in})
    return {"registered": True, "stamped": (REGISTRATION / "SHA256SUMS.ots").exists(), "changed": changed}


def describe(ch: dict) -> list[str]:
    """Lines for a report or a terminal."""
    if not ch["registered"]:
        return ["Registration: none found (prereg/registration/SHA256SUMS is missing)."]
    lines = ["Registration: " + ("stamped" if ch["stamped"] else "listed but not stamped") + "."]
    if not ch["changed"]:
        return lines + ["Every registered file matches the stamped list."]
    lines.append(f"{len(ch['changed'])} registered files differ from the stamped list:")
    for c in ch["changed"]:
        where = ", ".join(c["deviations"]) if c["deviations"] else "NO DEVIATION RECORD NAMES IT"
        lines.append(f"- `{c['file']}` ({c['state']}): {where}")
    return lines
