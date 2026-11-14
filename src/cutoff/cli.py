"""cutoff: build, dispatch, collect and analyze the Texas cutoff-format test.

    cutoff build [--check]      evidence files, prompts and design tables (build.py)
    cutoff status               what has run, by wave, family and arm
    cutoff dispatch [--wave N] [--family F] [--limit K] [--dry-run] [--pilot]
    cutoff collect              copy finished contexts into PRIVATE/contexts/, parse and audit them
    cutoff dryrun [--family F [--again]]
                                each model's dry run of the closed setup, which dispatch waits for
    cutoff tick                 collect, the dry runs, the replicate rule once wave 1 has finished, then dispatch
    cutoff flags [--clean KEY | --contaminated KEY] [--reason TEXT] [--reader WHO]
                                the blinded reading of prior_context texts (collect.py)
    cutoff replicates           apply the registered replicate rule to wave 1 (writes design/replicates.json)
    cutoff analyze              the registered analysis (outputs/); INTERIM while any context stays open
    cutoff registration [--write | --check]
                                the stamped list: write it once, or report every change since the stamp
    cutoff power                the planning table (outputs/power.md)
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cutoff", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--check", action="store_true")
    sub.add_parser("status")
    d = sub.add_parser("dispatch")
    d.add_argument("--wave", type=int, default=None)
    d.add_argument("--family", choices=("opus", "sol"), default=None)
    d.add_argument("--limit", type=int, default=None)
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--pilot", action="store_true", help="send one context for a family the pilot rule holds")
    sub.add_parser("collect")
    dr = sub.add_parser("dryrun")
    dr.add_argument("--family", choices=("opus", "sol"), default=None)
    dr.add_argument("--again", action="store_true", help="send one more dry run for the held family that --family names")
    sub.add_parser("tick")
    rg = sub.add_parser("registration")
    rg.add_argument("--write", action="store_true", help="write prereg/registration/SHA256SUMS over the registered files, once")
    rg.add_argument("--check", action="store_true", help="exit 1 if a changed file has no deviation record")
    fl = sub.add_parser("flags")
    fl.add_argument("--clean", default=None)
    fl.add_argument("--contaminated", default=None)
    fl.add_argument("--reason", default="")
    fl.add_argument("--reader", default="", help="who read the text: the model, and its Subfleet job if a lane read it")
    sub.add_parser("replicates")
    sub.add_parser("analyze")
    sub.add_parser("power")
    a = ap.parse_args(argv)

    if a.cmd == "build":
        from . import build

        b_ = build.build_all()
        for label in b_["skipped"]:
            print(f"skipped {label}: its sealed source files are not on this machine")
        if a.check:
            problems = build.check(b_)
            for p in problems:
                print(p)
            print("build check: " + ("FAILED" if problems else "every built file matches design/"))
            return 1 if problems else 0
        if b_["skipped"]:
            print("refusing to write a partial build; run with --check to verify what is here")
            return 1
        from . import store

        with store.lock():  # a tick checks the sandbox under the same lock
            for line in build.write(b_):
                print(line)
        return 0
    if a.cmd == "status":
        from . import collect

        print(collect.status_table())
        return 0
    if a.cmd == "dispatch":
        from . import dispatch

        return dispatch.main(wave=a.wave, family=a.family, limit=a.limit, dry_run=a.dry_run, pilot_ok=a.pilot)
    if a.cmd == "collect":
        from . import collect

        return collect.main()
    if a.cmd == "dryrun":
        from . import dryrun

        return dryrun.main(family=a.family, again=a.again)
    if a.cmd == "tick":
        from . import analysis, collect, dispatch, dryrun, store

        collect.main()
        dryrun.main()
        with store.lock():  # the rule runs as soon as wave 1 has finished, so no person picks the moment
            if analysis.replicates_due():
                analysis.write_replicates()
        return dispatch.main()
    if a.cmd == "registration":
        from . import registration

        if a.write:
            files = registration.write_list()
            print(f"wrote prereg/registration/SHA256SUMS over {len(files)} files; stamp it with OpenTimestamps")
            return 0
        ch = registration.changes()
        print("\n".join(registration.describe(ch)))
        return 1 if a.check and registration.unrecorded(ch) else 0
    if a.cmd == "flags":
        from . import collect

        if a.clean or a.contaminated:
            if not a.reason:
                print("give --reason")
                return 1
            return collect.decide(a.clean or a.contaminated, "clean" if a.clean else "contaminated", a.reason, a.reader)
        print(collect.READING_RULE + "\n")
        for key, rec in sorted(collect.flagged().items()):
            print(f"{key[:12]}  x{rec['count']}  {rec['decision'] or 'unread'}\n    {rec['text']}\n")
        return 0
    if a.cmd == "replicates":
        from . import analysis

        return analysis.write_replicates()
    if a.cmd == "analyze":
        from . import analysis

        return analysis.main()
    if a.cmd == "power":
        from . import power

        return power.main()
    return 2


if __name__ == "__main__":
    sys.exit(main())
