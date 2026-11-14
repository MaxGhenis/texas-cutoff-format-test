# Texas cutoff format test

A registered test of whether asking AI forecasters about one vote share at a time, instead of all six at once, changes their jumps at 50% in the 2026 Texas governor's race. README.md holds the registration.

## Rules for agents

- The registration froze on its OpenTimestamps stamp (`prereg/registration/`; `cutoff registration --write` wrote the list). After the stamp, a change to a listed file, or a new file beside them, needs a dated deviation in a new file under `prereg/` that names the file, the first twelve characters of its new SHA-256, and why. `cutoff registration --check` (CI runs it) fails while any change lacks one. `cutoff dispatch` refuses to run while a briefs or design file differs from the stamped list.
- Evidence files, prompts, screen logs, readers' sentence lists, context transcripts and `prior_context` texts quote news text. They live in `~/reviews/texas-cutoff-format-test/private/` (`CUTOFF_PRIVATE`) and never enter git. Publish only hashes, keys and numbers.
- The Sol runs' session logs (`runs/*/codex-sessions/rollout-*.jsonl` in the private Texas repository) carry the lanes' account details. Never copy them here or quote them.
- Models produced every forecast and jump under stated scenarios. Never describe a jump as an observation or an observed effect.
- `cutoff analyze` prints INTERIM while any context stays open. Quote no verdict from an interim run.
- Problems in `outputs/` publish counts, never a lane's paths, tool names, server names or a model's text.
- Run tests with `.venv/bin/pytest -n 4`, never more workers. Every test runs on MOCK records and starts no command. `uv sync --extra dev` builds the locked environment.
- Dispatch goes through `cutoff tick` (collect, the dry runs, the replicate rule once wave 1 has finished, then dispatch) on Subfleet's isolated lanes, never the OpenAI API. Never write or edit `design/replicates.json` by hand: `cutoff analyze` recomputes the rule and reports a record that disagrees.
- Dispatch sends nothing for a model until its dry run passes (`cutoff dryrun`). Two failed dry runs, three with no answer, or one read as contaminated hold the model: read them in the private store's `dryrun/` folder before you send the next with `cutoff dryrun --family <f> --again`. A dry run whose `prior_context` says more than "none" waits for the blinded reading (`cutoff flags`). A dry run counts only for the Subfleet arguments, prompt and folder notes it tried, so a change to any of them needs a new one; an earlier one still gets collected and ends as `superseded`.
- Until a model's first context passes, dispatch holds it after two failed answers or three attempts with no answer. Read those attempts' problems and answers before you send the next one with `cutoff dispatch --family <f> --limit 1 --pilot`; if the closed setup failed them, fix it under a dated deviation first. Dispatch also waits while the model's first answer awaits the blinded reading; the reading releases that wait, and `--pilot` does not.
- Every prompt opens with Subfleet's `<!-- subfleet:headless -->` marker, and the audit fails any context whose sent prompt differs from its registered prompt. Never strip the marker.
- The blinded `prior_context` reading (`cutoff flags`) prints the reader's rule, then each text and its key. Read it without opening the context's arm, share, model or answer, file by that rule, and never change a filed decision. The reader is an Opus 5.5 agent that sees only the command's output; file with `--reader` naming the model and, when a lane read it, its Subfleet job.
- Write in active voice with sentence-case headings. Read `~/.claude/projects/-Users-maxghenis/memory/voice_max.md` in full before editing README.md or anything else public.
