# Asking one vote share at a time: a registered test on Texas

On 3 November 2026, before Texas polls closed, research runs by Claude Opus 5.5 and GPT-6.1 Sol forecast what Texas would do about data centers under six results of the governor's race ([forecasts](https://github.com/MaxGhenis/texas-governor-data-center-forecasts)). Each run answered in one conversation at six shares of the two-party vote for Gina Hinojosa, the Democrat, from 44% to 56%. Six runs of each model gave answers that passed the Texas repository's check. Averaged over those runs, the models cut their chance that ERCOT resumes approving new data center loads by mid-2027 by 21.9 points (Opus) and 8.3 points (Sol) as Hinojosa's share crosses 50%. They raise their chance of a special session on data centers by 14.1 and 18.2 points.

People who forecast several treatments side by side predict larger effects than people who each forecast one, and the separate forecasts land closer to what happens ([Imas, Jung, Saccardo and Vosgerau 2022](https://www.nber.org/papers/w30611)). If language models do the same, asking for all six shares at once could inflate the jump. People who judge one option alone have a bias of their own: they give less weight to a quantity they find hard to judge in isolation ([Hsee, Loewenstein, Blount and Bazerman 1999](https://www.cmu.edu/dietrich/sds/docs/loewenstein/PrefRevJoint.pdf)). A forecaster who sees one share alone may find half a point of vote share hard to weigh. We ask the models the same questions three ways. We fixed every rule for running the three ways and comparing their answers before any model answered a brief here, and stamped the rules with OpenTimestamps in November 2026.

## The three arms

Every context, a fresh conversation with one model, reads one evidence file and answers three questions. We ask each context to forecast as if the official canvass gives Hinojosa a stated share of the two-party vote for governor against Greg Abbott, the Republican incumbent.

- In the **grid** arm, one context answers all three questions at all six shares, as the research runs answered all thirteen of their questions.
- In the **alone** arm, each context gets one share and forecasts under that scenario only.
- In the **told** arm, each context gets one share and one more sentence, which names the six shares and says that separate conversations answer the same questions, each seeing only its own.

The six shares sit at 44%, 47%, 49.5%, 50.5%, 53% and 56%. The two primary questions ask for probabilities, and the secondary one for five quantiles:

- `ercot_pause_lifted` (primary): by 30 June 2027, ERCOT resumes approving new data center Large Loads to energize.
- `special_session_data_centers` (primary): by 31 December 2027, the governor calls a special session that takes up data centers.
- `senate_dem_share` (secondary): James Talarico's certified share of the two-party vote for US Senate.

[`scripts/make_briefs.py`](scripts/make_briefs.py) writes the three briefs in [`briefs/`](briefs/) from the research runs' brief. It copies the question blocks and the whole Context section word for word, names an isolated brief's one share in its blocks, and lists each change. Each prompt opens with one HTML comment, `<!-- subfleet:headless -->`. Without it, Subfleet, the job runner that sends each context to its model, would put a note on running headless ahead of every Opus prompt, and the two models would read different text. Opus 5.5 (`claude-opus-5-5`) answers through Claude Code and GPT-6.1 Sol (`gpt-6.1-sol`, ultra effort) through Codex, and each of the 16 evidence files goes to both models. At three contexts a share, each file and model takes 3 grid contexts and 18 in each of the other two arms, so we start with 1,248 contexts. `cutoff replicates` can raise that to six contexts a share, 2,496 contexts.

## The evidence files

The research runs searched the web, and the contexts here can't. Each context instead reads an evidence file: the text that one research run's web tools returned on 3 November, in the order the run read it. A file holds search results and the text or extracts of pages, and nothing the run wrote itself: no queries, fetch prompts, reasoning, sub-agent reports or answers. Ten files come from the Opus runs' transcripts, which we publish in the Texas repository. Six come from the Sol runs' session logs, which hold account details and stay private. [`design/files.json`](design/files.json) records the hash of every source file, and the build checks each against the manifests we stamped in the Texas repository on 3 November.

Each Sol run also sent three sub-agents to search, and their reading came to 2.4 to 5.9 times the main thread's. Adding it would more than triple the text the contexts read, so a Sol file holds the main thread's reading only.

[`src/cutoff/evidence.py`](src/cutoff/evidence.py) builds each file in four steps:

1. It drops the tools' bookkeeping, such as citation markers, line numbers, error notices and lines that hold only links.
2. It splits each line into sentences and drops every sentence that matches a screen rule. The rules cover prediction markets and odds, forecasts and ratings of a race, chances and probabilities, and words of expectation. They also cover statements of what the election's result would do, and a tool speaking back to the session that called it. A candidate's or campaign's statement of what they will do stays. The runs wrote their searches with the questions in mind, so a tool's summary can hold a forecast that no source stated, and the screen drops those too. It drops an item whole when a quarter or more of its sentences, and at least two, match the betting-markets rule. It also drops an extract whose first line says the tool could not read the page.
3. It applies readers' corrections. Claude agents (Fable 5.2 and Opus 5.5) read every file after the rules ran, and every sentence and item the rules drop. [`design/reader_removals.csv`](design/reader_removals.csv) lists 27 sentences that go although no rule matches them. [`design/reader_keeps.csv`](design/reader_keeps.csv) lists 73 that stay although a rule matches them, such as an official body's schedule or a poll's numbers. Both lists hold SHA-256 hashes, since the sentences quote news text.
4. It keeps the first copy of each line.

The Opus files run from 32,000 to 58,000 characters and the Sol files from 100,000 to 224,000. The build turns the same sealed logs into the same bytes, and `design/files.json` records each file's hash.

## Closed contexts

Each context runs through Subfleet in its isolated mode, on one of the subscription accounts Subfleet draws on (a lane), with a pinned model and a read-only session that has no shell. It works in a folder whose path names nothing about the study and which holds two short notes and nothing else. [`src/cutoff/audit.py`](src/cutoff/audit.py) reads the records Subfleet keeps and passes a context only when:

- it called no tool;
- the prompt it received matches its registered prompt, byte for byte;
- it worked in that folder;
- for Opus, the launch pinned `claude-opus-5-5`, offered only the three file-reading tools in plan mode, and loaded no settings, memory or MCP server; every message names that model; and Subfleet attests the model that served it;
- for Sol, the launch pinned `gpt-6.1-sol` at ultra effort in an ephemeral, read-only session, with user configuration, rules, project instructions, web search and multi-agent mode off, and the stream holds one turn.

The two notes in the folder, `CLAUDE.md` and `AGENTS.md`, each ask their reader to write a code word in the answer. A provider that loads project instructions would show a note to the context, and an answer that carries the code word fails. Rule 8 of every brief also asks the context whether anything it can see besides the brief mentions the race, data centers or these forecasts. The context describes what it finds in `forecaster.prior_context`, or writes "none".

## Which answers count

An answer counts when its context passes the audit and the answer fills its brief's template ([`src/cutoff/response.py`](src/cutoff/response.py)). It needs a number at every share its brief names: a probability from 0 to 1, or Talarico quantiles that never decrease and stay within 30% to 70%. A context in the alone or told arm also restates its scenario, and the restated share has to match its own within 0.05 points, with the right winner. We read each answer as written first. Only an answer that fails gets the two registered repairs, the same in every arm. We drop trailing commas that stop the JSON from parsing, and keys the template lacks whose values hold no object. An answer that needs any other change fails.

An answer whose `prior_context` says anything more than a bare "none", "nothing" or "n/a" waits for a blinded reading. An Opus 5.5 agent sees each distinct text and its key, without its arm, share, model or forecast, and files `clean` or `contaminated` with a reason (`cutoff flags`). It files `contaminated` when the text shows that the model saw something besides its prompt that bears on its answer. That covers a note or file in its folder, an instruction from a memory or settings file, and anything about the race, data centers or these forecasts. A text that shows nothing of that kind gets `clean`, as when a model restates its prompt or declines to describe its provider's system prompt. A clean answer passes, a contaminated one fails, and a filed decision stands. `review/prior_context.csv` will hold each key, decision and reason, and the texts stay private, since they can quote the evidence.

When an answer fails, a fresh context replaces it, at most twice, and when a run ends with no answer, as when a lane fails, the context runs again. A context stops, and adds nothing, after three failed answers or five runs with no answer. A job that Subfleet cancels before any lane starts it never ran and counts toward neither limit. We also run the analysis without repaired answers and without answers that needed the reading, and report that strict version beside the main one.

## Dry runs and first contexts

Before any context goes out, each model answers one dry-run prompt on one of its lanes ([`src/cutoff/dryrun.py`](src/cutoff/dryrun.py)). The prompt asks for the product of two numbers, and whether anything the model can see besides the prompt mentions arithmetic or asks for a particular word. It names nothing about the study, and it goes through the same launch, folder and audit as a context. A dry run passes when the audit passes, the product comes out right, the answer leaves out the code word and `prior_context` says "none". Any other text goes to the blinded reading, where a note about arithmetic or a word to write counts as contaminated. A dry run counts only for the launch, prompt and notes it tried, so we run a new one when any of them changes. Dispatch holds each model until its dry run passes. Two failed dry runs, three that end with no answer, or one text read as contaminated stop that model until we read them.

Then, until a model's first context passes, its contexts run one at a time. If two answers fail, or three runs end with no answer, before any passes, that model stops until we read them and send the next one by hand. The model also waits while its first answer awaits the reading. So when a fault that every lane shares fails answers, loses runs or shows in `prior_context`, it costs a few runs while the model's other contexts wait.

## Order and replicates

Contexts run in three waves, each in a seeded random order, so arms, shares and models interleave in time ([`src/cutoff/design.py`](src/cutoff/design.py): seed 20261110 draws the first batch, and 20261111 sets the order).

- The first batch, wave 1, runs two files the seed drew, one from the accepted Opus runs and one from the Sol runs (`opus-9` and `sol-4`), in every arm for both models at three contexts a share: 156 contexts.
- Wave 2 runs the other 14 files at three contexts a share, 1,092 contexts. A model's wave 2 starts once all its wave 1 contexts have finished running.
- Wave 3 runs contexts four to six at each share for every file, up to the number the replicate rule picks.

When wave 1 finishes, its readings included, `cutoff replicates` measures two spreads for each model and primary question. One covers answers within a share in the alone and told arms, and the other the grid contexts' jumps. From them it projects the standard error of each primary difference at three to six contexts a share. It picks the smallest number at which both primaries' projected error falls to 1.65 points or less. At that error, the equivalence test has about an 80% chance of passing when the arms agree on every file. The projection counts the noise within files and leaves out any spread of a true difference across them. If no number gets there, it picks six. It writes its choice to `design/replicates.json` once, and dispatch never sends past it. [`outputs/power.md`](outputs/power.md) gives the planning table.

## The analysis

`cutoff analyze` runs [`src/cutoff/analysis.py`](src/cutoff/analysis.py) on the passed answers (`outputs/answers.csv`) and the research runs' own jumps ([`design/reference.json`](design/reference.json)). We express probabilities in points, and a Talarico answer as the mean of the distribution its five quantiles describe ([`src/cutoff/jump.py`](src/cutoff/jump.py)).

### Jumps

For each file, model, arm and question, we take the mean answer at each share and fit a least-squares line through the three shares on each side of 50%. The jump measures the gap between the two lines at 50%, Hinojosa's side minus Abbott's, which makes it a fixed weighted sum of the six means:

J = 0.8901 (y50.5 − y49.5) + 0.3681 (y53 − y47) − 0.2582 (y56 − y44)

We multiply each jump by its question's registered direction, so a positive signed jump points the registered way. We registered −1 for ERCOT, where we expect a Hinojosa win to lower the chance, and +1 for the special session. Talarico's share has no registered direction and keeps its sign.

### Differences and tests

Within each model, we subtract one arm's signed jump from another's for each file, then average over the models whose bridge holds. We treat the file as the unit, since contexts that read one file share its evidence. A file drops out of a difference unless every pooled model has a jump in both arms for it. We average the files' differences, take the standard error from their spread, and use a t distribution with one fewer degree of freedom than files. We compare alone with grid, told with grid, and told with alone.

Each difference gets a two-sided test of zero and an equivalence test against its question's margin: two one-sided tests at 5%, which pass when the 90% interval falls inside plus or minus the margin. The margins come to 5 points for ERCOT and for the special session, about a third of the two models' average jump on each, and 0.1 points for Talarico's share. The two primary differences, alone minus grid on ERCOT and on the special session, take Holm's adjustment for each kind of test. A primary with no pooled result enters the adjustment with a p-value of 1. Each primary then gets one verdict: equivalent if its adjusted equivalence p-value falls below 0.05, different if its adjusted p-value against zero does, and unresolved otherwise. When both adjusted p-values fall below 0.05, the verdict reads equivalent, because the difference stays inside the margin even though it departs from zero.

### The bridge

We can carry the arms' results over to the research runs' jumps only if the evidence files hold what drove those jumps. For each model and question, we take the grid jump of each accepted research run's own file, answered by the same model, and subtract that run's own jump. Each model has six accepted runs, the six whose answers passed our check in the Texas repository: `opus-1`, `opus-3`, `opus-4`, `opus-8`, `opus-9` and `opus-10`, and `sol-1` to `sol-6`. The bridge holds when every accepted run has a grid jump and the mean difference falls within the margin. A model whose bridge fails on a primary question drops out of that question's pooled differences, and we still report its own differences. A bridge as tight as 0.1 points can fail on noise alone, so we pool both models on Talarico's share whatever its bridge shows, and report the bridge beside them. Each bridge difference also takes in what the contexts lack: the web, the ten other questions the research runs answered, and the sentences the screen drops.

### Research against reasoning

Each file goes to both models. Over the twelve accepted runs' files, we tabulate grid jumps by whose research a file holds and which model answers. From that table we split the gap between the models into a part from their research and a part from their reasoning.

### What we report

One table holds all three arms with the models pooled, and another gives each model alone. When we report the research runs' Texas jumps, we give the grid's jump alone in the abstract only if both primary verdicts read equivalent and both told-minus-grid intervals fall inside the margin. Otherwise we give the grid's and the alone arm's jumps side by side.

## Limits

- Equivalence within 0.1 points on Talarico's share needs a standard error below 0.057 points. Even at six contexts a share and with no spread across files, answers within a share would have to spread less than 0.4 points. So Talarico's share takes no verdict, and we report its differences with their intervals.
- An isolated, ephemeral Codex session leaves no record of the model that served it, so for Sol we rely on the launch pin. Subfleet attests every Opus serve.
- We decide which models pool on a primary from the same grid contexts that enter the differences. When noise pulls a model's grid jumps toward its research runs' jumps, the model passes more easily, and the same noise enters alone minus grid with the opposite sign. So the pooled difference can lean slightly.
- A Sol file holds less than its run read. The bridge shows whether each model, reading its own runs' files, still gives those runs' jumps, with that loss and every other difference from the research runs included.
- When the screen drops a betting-odds item whole, it drops the facts in it too. The reading agents found three: two sets of poll numbers and how long Republicans have held the governorship.
- Models produced every number here under stated scenarios. A jump measures how their forecasts change across 50%, not an effect anyone observed.

## Files

This repository holds the briefs, the design tables in [`design/`](design/), the code, the tests and the outputs. The evidence files, the prompts, the screen logs, the readers' sentence lists, every context's records and the `prior_context` texts quote news text, so they stay in a private folder outside the repository (`CUTOFF_PRIVATE`). The design tables record their hashes.

To rebuild the ten Opus evidence files and their prompts and check each hash, clone the [Texas repository](https://github.com/MaxGhenis/texas-governor-data-center-forecasts) to `~/texas-governor-data-center-forecasts` (or point `CUTOFF_PUBLIC_TEXAS` at it) and run:

```bash
uv venv && uv pip install -e '.[dev]'
```

```bash
.venv/bin/cutoff build --check
```

```bash
.venv/bin/pytest -n 4
```

The six Sol files need the private session logs. [`src/cutoff/cli.py`](src/cutoff/cli.py) lists the other commands: `status`, `dryrun`, `dispatch`, `collect`, `tick`, `flags`, `replicates`, `analyze` and `power`. A scheduled job runs `tick` every five minutes: it collects finished contexts, sends any dry run that falls due, then dispatches.

## The registration

`prereg/registration/SHA256SUMS` lists the SHA-256 of this README, the briefs, every file in `design/`, `outputs/power.md`, the code in `src/` and `scripts/`, the tests and `pyproject.toml`. `prereg/registration/SHA256SUMS.ots` timestamps that list in Bitcoin through [OpenTimestamps](https://opentimestamps.org). `cutoff dispatch` refuses to send a context unless both files exist and the briefs and the four design tables that name the stimulus (`prompts.csv`, `contexts.csv`, `files.json` and `sandbox.json`) still match the list. It also checks each prompt file against its hash in `design/prompts.csv`, and refuses while the contexts' folder holds anything besides the two notes. `cutoff analyze` and `cutoff replicates` run either way, but their output lists every registered file that differs from the list, beside the dated deviation records in `prereg/` that name it. Anyone can check every file against the list from the repository's root:

```bash
shasum -a 256 -c prereg/registration/SHA256SUMS
```

To check the stamp once Bitcoin has confirmed it:

```bash
uvx --from opentimestamps-client ots upgrade prereg/registration/SHA256SUMS.ots
```

```bash
uvx --from opentimestamps-client ots verify prereg/registration/SHA256SUMS.ots
```

MIT license.
