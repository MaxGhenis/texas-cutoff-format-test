"""Where the study reads its sealed sources and keeps the files that stay out of git.

The evidence files, the prompts that carry them and every context's transcript quote news text, so
they live in PRIVATE, outside the repository; `design/` records their SHA-256, and `outputs/` gets
every context's numbers. The Opus runs' sealed
transcripts sit in the public Texas repository, so anyone can rebuild those ten evidence files. The
Sol runs' session logs carry the lanes' account details and sit only in the private Texas repository.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()


def _env(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


PUBLIC_TEXAS = _env("CUTOFF_PUBLIC_TEXAS", HOME / "texas-governor-data-center-forecasts")
PRIVATE_TEXAS = _env("CUTOFF_PRIVATE_TEXAS", HOME / "tx-gov-datacenter-forecast")
PRIVATE = _env("CUTOFF_PRIVATE", HOME / "reviews" / "texas-cutoff-format-test" / "private")
# A closed context sees its working folder's path, so the path names nothing about the study (the sealed
# Sol runs quoted theirs, which named the subject).
SANDBOX = _env("CUTOFF_SANDBOX", HOME / ".cache" / "sbx-1110" / "work")
JOBS = _env("CUTOFF_SUBFLEET_JOBS", HOME / ".subfleet" / "jobs")
DESIGN = ROOT / "design"
BRIEFS = ROOT / "briefs"
OUTPUTS = ROOT / "outputs"
