"""Every test runs against its own temporary store: no test reads or writes the real private store, the
sandbox, Subfleet's job folders or the public review file. `subprocess.run` raises, so no test starts
a study command; the registration's scope reads `git ls-files`, read-only, through Popen."""

from __future__ import annotations

import subprocess

import pytest

from cutoff import collect, paths, registration


@pytest.fixture(autouse=True)
def isolated_store(tmp_path_factory, monkeypatch):
    root = tmp_path_factory.mktemp("store")
    for name in ("PRIVATE", "OUTPUTS", "SANDBOX", "JOBS"):
        monkeypatch.setattr(paths, name, root / name.lower())
    monkeypatch.setattr(collect, "PRIOR_REVIEW", root / "review" / "prior_context.csv")
    monkeypatch.setattr(registration, "REGISTRATION", root / "prereg" / "registration")
    monkeypatch.setattr(registration, "SCOPE", ())  # a test that checks the list's coverage sets its own

    def refuse(*args, **kwargs):
        raise AssertionError(f"a test tried to run a command: {args[0] if args else kwargs}")

    monkeypatch.setattr(subprocess, "run", refuse)
    yield root
    # A test that undid these patches (`monkeypatch.undo()`) would have worked on the real folders.
    for folder in (paths.PRIVATE, paths.OUTPUTS, paths.SANDBOX, paths.JOBS, collect.PRIOR_REVIEW, registration.REGISTRATION):
        assert str(folder).startswith(str(root)), f"a test left the temporary store: {folder}"
