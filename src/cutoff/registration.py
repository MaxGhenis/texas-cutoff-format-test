"""The stamped registration and the checks against it.

`prereg/registration/SHA256SUMS` lists a SHA-256 for every registered file (`scope`), and
`SHA256SUMS.ots` timestamps that list. `write_list` writes the list once, from the files as they
stand. Dispatch refuses to send a context while any stimulus file differs from the list (`problems`).
The analysis and the replicate rule run either way, but they list every registered file that changed
since the stamp and every file added to the registered folders, with the deviation records under
`prereg/` that name it (`changes`), so a changed rule can't run unseen. A record names a change when
it holds the file's path and the first twelve characters of its new SHA-256, so a record for one
change does not cover the next.
"""

from __future__ import annotations

import hashlib

from . import paths

REGISTRATION = paths.ROOT / "prereg" / "registration"
# What the registration covers: the README, the briefs, the design tables, the planning table, the
# code, the tests and the environment. `design/replicates.json` comes after the stamp, from the rule.
SCOPE = ("README.md", "pyproject.toml", "uv.lock", "outputs/power.md", "briefs/*.md", "design/*", "src/cutoff/*.py",
         "scripts/*.py", "tests/*.py")  # fmt: skip
AFTER_THE_STAMP = ("design/replicates.json",)
# What a dispatch needs unchanged since the stamp: the stimulus and the tables that name it.
STIMULUS = ("briefs/grid.md", "briefs/alone.md", "briefs/told.md", "design/prompts.csv", "design/contexts.csv",
            "design/files.json", "design/sandbox.json")  # fmt: skip


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scope() -> list[str]:
    """The registered files as they stand on disk, by path from the repository's root."""
    found = {p.relative_to(paths.ROOT).as_posix() for pattern in SCOPE for p in paths.ROOT.glob(pattern) if p.is_file()}
    return sorted(found - set(AFTER_THE_STAMP))


def write_list() -> list[str]:
    """Write SHA256SUMS over `scope()`, in `shasum -a 256` format. It writes once: a list that exists
    stands, and a change after it needs a deviation record."""
    target = REGISTRATION / "SHA256SUMS"
    if target.exists():
        raise SystemExit("prereg/registration/SHA256SUMS exists already; record a change as a dated deviation")
    files = scope()
    missing = [rel for rel in STIMULUS if rel not in files]
    if missing:
        raise SystemExit(f"stimulus files are missing: {missing}")
    REGISTRATION.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{sha(paths.ROOT / rel)}  {rel}\n" for rel in files))
    return files


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
    listed = manifest()
    found = {rel: _state(rel, digest) for rel, digest in listed.items()}
    found.update({rel: "unlisted" for rel in scope() if rel not in listed})  # added after the stamp
    changed = []
    for rel, state in sorted(found.items()):
        if state is None:
            continue
        # A record covers this change when it names the file and its present hash (or, for a file that
        # is gone, the file alone).
        mark = "" if state == "missing" else sha(paths.ROOT / rel)[:12]
        named_in = [f"prereg/{p.name}" for p, text in records if rel in text and mark in text]
        changed.append({"file": rel, "state": state, "deviations": named_in})
    return {"registered": True, "stamped": (REGISTRATION / "SHA256SUMS.ots").exists(), "changed": changed}


def unrecorded(ch: dict) -> list[str]:
    """The changed files that no deviation record covers."""
    return [c["file"] for c in ch["changed"] if not c["deviations"]]


def describe(ch: dict) -> list[str]:
    """Lines for a report or a terminal."""
    if not ch["registered"]:
        return ["Registration: none found (prereg/registration/SHA256SUMS is missing)."]
    lines = ["Registration: " + ("stamped" if ch["stamped"] else "listed but not stamped") + "."]
    if not ch["changed"]:
        return lines + ["Every registered file matches the stamped list, and the list covers every registered file."]
    lines.append(f"{len(ch['changed'])} registered files differ from the stamped list:")
    for c in ch["changed"]:
        where = ", ".join(c["deviations"]) if c["deviations"] else "NO DEVIATION RECORD NAMES IT"
        lines.append(f"- `{c['file']}` ({c['state']}): {where}")
    return lines
