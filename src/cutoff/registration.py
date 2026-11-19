"""The stamped registration and the checks against it.

`prereg/registration/SHA256SUMS` lists a SHA-256 for every registered file (`scope`), and
`SHA256SUMS.ots` timestamps that list. `write_list` writes the list once, from the files as they
stand. Dispatch refuses to send a context while any stimulus file differs from the list (`problems`).
The analysis and the replicate rule run either way, but they list every registered file that changed
since the stamp and every file added to the registered folders, with the deviation records under
`prereg/` that name it (`changes`), so a changed rule can't run unseen. A record names a change when
it holds the file's path and the first twelve characters of its new SHA-256 (or, for a file that is
gone, the path and the word "removed"), so a record for one change does not cover the next.

The proof binds the list: an OpenTimestamps proof opens with the SHA-256 of the file it stamps
(`stamped_digest`), and every check here fails a list whose hash differs from it. So nobody can edit
or rewrite the list after the stamp without the checks saying so.
"""

from __future__ import annotations

import hashlib
import subprocess

from . import paths

REGISTRATION = paths.ROOT / "prereg" / "registration"
# What the registration covers: the README, the briefs, the design tables, the planning table, the
# code, the tests and the environment. `design/replicates.json` comes after the stamp, from the rule.
SCOPE = ("README.md", "pyproject.toml", "uv.lock", "outputs/power.md", ".github/workflows/ci.yml", "briefs/", "design/",
         "src/", "scripts/", "tests/")  # fmt: skip
AFTER_THE_STAMP = ("design/replicates.json",)
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
# What a dispatch needs unchanged since the stamp: the stimulus and the tables that name it.
STIMULUS = ("briefs/grid.md", "briefs/alone.md", "briefs/told.md", "design/prompts.csv", "design/contexts.csv",
            "design/files.json", "design/sandbox.json")  # fmt: skip


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked() -> list[str] | None:
    """The files git tracks under the repository's root, or None where git cannot say (no checkout)."""
    if not (paths.ROOT / ".git").exists():
        return None
    try:
        proc = subprocess.Popen(["git", "-C", str(paths.ROOT), "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out, _ = proc.communicate(timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return [name for name in out.decode().split("\0") if name] if proc.returncode == 0 else None


def scope() -> list[str]:
    """The registered files, by path from the repository's root: every file git tracks under `SCOPE`
    (a folder at any depth, or a named file), so a stray file an editor or the system left beside them
    never enters the list. Without a git checkout it reads the disk and skips hidden and cache files."""
    names = _tracked()
    if names is None:
        names = [p.relative_to(paths.ROOT).as_posix() for p in paths.ROOT.rglob("*") if p.is_file()]
        names = [n for n in names if not any(part.startswith(".") or part == "__pycache__" for part in n.split("/")[:-1])
                 and not n.split("/")[-1].startswith(".") and not n.endswith(".pyc")] + [
                     n for n in (".github/workflows/ci.yml",) if (paths.ROOT / n).is_file()]  # fmt: skip
    found = {n for n in names if any(n == s or (s.endswith("/") and n.startswith(s)) for s in SCOPE) and (paths.ROOT / n).is_file()}
    return sorted(found - set(AFTER_THE_STAMP))


def stamped_digest() -> str | None:
    """The SHA-256 that the OpenTimestamps proof commits to, read from the proof's own header: the
    magic bytes, a version byte, the hash operation (08 for SHA-256) and the digest. None when the
    proof is missing or does not open that way."""
    proof = REGISTRATION / "SHA256SUMS.ots"
    if not proof.exists():
        return None
    data = proof.read_bytes()
    head = len(OTS_MAGIC)
    if not data.startswith(OTS_MAGIC) or len(data) < head + 34 or data[head + 1] != 0x08:
        return None
    return data[head + 2 : head + 34].hex()


def stamp_problems() -> list[str]:
    """Why the list and its proof do not stand together (empty when they do)."""
    if not (REGISTRATION / "SHA256SUMS").exists():
        return ["no registration: prereg/registration/SHA256SUMS is missing"]
    if not (REGISTRATION / "SHA256SUMS.ots").exists():
        return ["the registration has no OpenTimestamps stamp (SHA256SUMS.ots)"]
    digest = stamped_digest()
    if digest is None:
        return ["SHA256SUMS.ots does not read as an OpenTimestamps proof of a SHA-256"]
    if digest != sha(REGISTRATION / "SHA256SUMS"):
        return ["SHA256SUMS differs from the list its OpenTimestamps proof stamps"]
    return []


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
    """The list as {path: digest}. A line that does not read as a digest and a path gets the key
    `unreadable line N`, which no file matches, so every check reports it."""
    out = {}
    for n, line in enumerate((REGISTRATION / "SHA256SUMS").read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].strip()] = parts[0]
        else:
            out[f"unreadable line {n}"] = ""
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
    out = stamp_problems()
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
        # A proof without its list means someone removed the list: that is a change, not a clean slate.
        orphan = (REGISTRATION / "SHA256SUMS.ots").exists()
        return {"registered": False, "stamped": False, "stamp_problems": stamp_problems() if orphan else [], "changed": []}
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
        mark = "removed" if state == "missing" else sha(paths.ROOT / rel)[:12]
        named_in = [f"prereg/{p.name}" for p, text in records if rel in text and mark in text]
        changed.append({"file": rel, "state": state, "deviations": named_in})
    problems = stamp_problems()
    return {"registered": True, "stamped": not problems, "stamp_problems": problems, "changed": changed}


def unrecorded(ch: dict) -> list[str]:
    """What stands against the registration with no deviation record: each changed file that no record
    covers, and any fault in the list or its proof (which no record can cover)."""
    return [c["file"] for c in ch["changed"] if not c["deviations"]] + list(ch.get("stamp_problems", []))


def describe(ch: dict) -> list[str]:
    """Lines for a report or a terminal."""
    if not ch["registered"]:
        if ch.get("stamp_problems"):
            return ["Registration: the proof stands without its list (prereg/registration/SHA256SUMS is missing)."]
        return ["Registration: none found (prereg/registration/SHA256SUMS is missing)."]
    if ch["stamped"]:
        lines = ["Registration: stamped, and the list matches its proof."]
    else:
        lines = ["Registration: NOT STAMPED: " + "; ".join(ch.get("stamp_problems") or ["no proof"]) + "."]
    if not ch["changed"]:
        return lines + ["Every registered file matches the list, and the list covers every registered file."]
    n = len(ch["changed"])
    lines.append(f"{n} registered file{'s differ' if n != 1 else ' differs'} from the list:")
    for c in ch["changed"]:
        where = ", ".join(c["deviations"]) if c["deviations"] else "NO DEVIATION RECORD NAMES IT"
        lines.append(f"- `{c['file']}` ({c['state']}): {where}")
    return lines
