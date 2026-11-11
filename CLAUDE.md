# Texas cutoff format test

A registered test of whether asking AI forecasters about one vote share at a time, instead of all six at once, changes their jumps at 50% in the 2026 Texas governor's race. README.md holds the registration.

## Rules for agents

- The registration froze on its OpenTimestamps stamp (`prereg/registration/`). After the stamp, never edit a file that `SHA256SUMS` lists. Record any change as a dated deviation in a new file under `prereg/`, and say why. `cutoff dispatch` refuses to run while a briefs or design file differs from the stamped list.
- Evidence files, prompts, screen logs, readers' sentence lists, context transcripts and `prior_context` texts quote news text. They live in `~/reviews/texas-cutoff-format-test/private/` (`CUTOFF_PRIVATE`) and never enter git. Publish only hashes, keys and numbers.
- The Sol runs' session logs (`runs/*/codex-sessions/rollout-*.jsonl` in the private Texas repository) carry the lanes' account details. Never copy them here or quote them.
- Models produced every number under stated scenarios. Never describe a jump as an observation or an observed effect.
- Run tests with `.venv/bin/pytest -n 4`, never more workers. Every test runs on MOCK records and starts no command.
- Dispatch goes through `cutoff tick` (collect, the dry runs, then dispatch) on Subfleet's isolated lanes, never the OpenAI API.
- Dispatch sends nothing for a model until its dry run passes (`cutoff dryrun`). Two failed dry runs, or three with no answer, hold the model: read them in the private store's `dryrun/` folder before you send the next with `cutoff dryrun --family <f> --again`. A dry run whose `prior_context` says more than "none" waits for the blinded reading (`cutoff flags`).
- Until a model's first context passes, dispatch holds it after two failed answers or three runs with no answer. Read those attempts' problems and answers before you send the next one with `cutoff dispatch --family <f> --limit 1 --pilot`; if the closed setup failed them, fix it under a dated deviation first.
- Every prompt opens with Subfleet's `<!-- subfleet:headless -->` marker, and the audit fails any context whose sent prompt differs from its registered prompt. Never strip the marker.
- The blinded `prior_context` reading (`cutoff flags`) shows only the text and its key. Read it without opening the context's arm, share, model or answer, and never change a filed decision.
- Write in active voice with sentence-case headings. Read `~/.claude/projects/-Users-maxghenis/memory/voice_max.md` in full before editing README.md or anything else public.
