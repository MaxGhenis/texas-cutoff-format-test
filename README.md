# Asking one vote share at a time: a registered test on Texas

On 3 November 2026, before Texas polls closed, research runs by Claude Opus 5.5 and GPT-6.1 Sol forecast what Texas would do about data centers under six results of the governor's race ([the Texas repository](https://github.com/MaxGhenis/texas-governor-data-center-forecasts)). Each run answered in one conversation at six shares of the two-party vote for Gina Hinojosa, the Democrat, from 44% to 56%. Six runs of each model, the accepted runs, gave answers that passed the Texas repository's schema check. As Hinojosa's share crosses 50%, the models cut their chance that ERCOT, Texas's main grid operator, resumes approving new data center loads by mid-2027. On average over those runs, Opus cuts it by 21.9 points and Sol by 8.3, and they raise their chance of a special session on data centers by 14.1 and 18.2 points. We get each figure, a jump at 50%, by fitting a line to a model's forecasts on each side of 50% and taking the gap between the two lines there.

People who forecast several treatments side by side predict larger effects than people who each forecast one, and the separate forecasts land closer to what happens ([Imas, Jung, Saccardo and Vosgerau 2022](https://www.nber.org/papers/w30611)). If language models do the same, asking for all six shares at once could inflate the jump at 50%. People who judge one option alone, though, give less weight to a quantity they find hard to judge in isolation ([Hsee, Loewenstein, Blount and Bazerman 1999](https://www.cmu.edu/dietrich/sds/docs/loewenstein/PrefRevJoint.pdf)). A forecaster who sees one share alone may find half a point of vote share hard to weigh. We ask the models the same questions three ways: all six shares in one conversation, one share per conversation, and one share per conversation with two sentences about the others. We fixed every rule for running the three ways and comparing their answers before any model answered the questions, and stamped the rules with OpenTimestamps in November 2026.

## The three arms

Every context gives one model one prompt in a fresh conversation: the model reads one evidence file, the text that one research run's web tools returned, and answers three questions. We ask each context to forecast as if the official canvass gives Hinojosa a stated share of the two-party vote for governor against Greg Abbott, the Republican incumbent.

- In the **grid** arm, one context answers all three questions at all six shares, as the research runs answered eleven of their thirteen questions.
- In the **alone** arm, each context gets one share and forecasts under that scenario only.
- In the **told** arm, each context gets one share and two more sentences, which name the six shares and say that separate conversations answer the same questions, each seeing only its own. The sentence after them says "under yours" where the alone brief says "under that scenario".

The six shares sit at 44%, 47%, 49.5%, 50.5%, 53% and 56%. The two primary questions ask for probabilities. The secondary one, a placebo, asks for five quantiles of a Senate vote on the same ballot: the governor's result cannot cause it, so its forecasts can climb with Hinojosa's share and should not jump at 50%.

- `ercot_pause_lifted` (primary): by 30 June 2027, ERCOT resumes approving new data center Large Loads to energize.
- `special_session_data_centers` (primary): by 31 December 2027, the governor calls a special session that takes up data centers.
- `senate_dem_share` (secondary): the certified share of the two-party vote for US Senate that goes to James Talarico, the Democrat.

[`scripts/make_briefs.py`](scripts/make_briefs.py) writes the three briefs in [`briefs/`](briefs/) from the research runs' brief. It copies the question blocks and the whole Context section word for word, names the one share of each alone and told brief in its blocks, and its docstring lists every other change. [`src/cutoff/prompts.py`](src/cutoff/prompts.py) builds each prompt from a brief, its scenario and an evidence file, and opens it with one HTML comment, `<!-- subfleet:headless -->`. Subfleet, the job runner that sends each context to its model, puts a line on running headless ahead of any Opus prompt that lacks that comment. With the comment in place, both models read the same text. Opus 5.5 (`claude-opus-5-5`) answers through Claude Code and GPT-6.1 Sol (`gpt-6.1-sol`, ultra effort) through Codex, and each of the 16 evidence files goes to both models. At three contexts a share, each file and model takes 3 grid contexts and 18 in each of the other two arms, so we start with 1,248 contexts. After the first 156, a registered rule can raise that to as many as six contexts a share, 2,496 contexts.

## The evidence files

The research runs searched the web, and the contexts cannot. Each context instead reads an evidence file: the text that one research run's web tools returned on 3 November, in the order the run read it. A file holds search results and the text or extracts of pages, and nothing the run wrote itself: no queries, fetch prompts, reasoning, sub-agent reports or answers. Ten files come from the Opus runs' transcripts, which we publish in the Texas repository. Six come from the Sol runs' session logs, which hold account details and stay private. [`design/files.json`](design/files.json) records the hash of every source file, and `cutoff build` checks each against the manifests we stamped in the Texas repository on 3 November.

Each Sol run also sent three sub-agents to search, and the text their tools returned came to 2.4 to 5.9 times the main thread's. If we added it, a Sol context would read more than three times as much text, so a Sol file holds the main thread's text only.

[`src/cutoff/evidence.py`](src/cutoff/evidence.py) builds each file in four steps:

1. It drops the tools' bookkeeping, such as citation markers, line numbers, error notices and lines that hold only links.
2. It splits each line into sentences and drops every sentence that matches a screen rule. The rules cover prediction markets and odds, forecasts and ratings of a race, chances and probabilities, and words of expectation. They also cover statements of what the election's result would do, and a tool speaking back to the session that called it. A candidate's or campaign's statement of what they will do stays. The runs wrote their searches with the questions in mind, so a tool's summary can hold a forecast that no source stated, and the screen drops such forecasts too. It drops an item, one search result or page extract, whole when a quarter or more of its sentences, and at least two, match the rule on prediction markets and odds. It also drops an extract whose first line says the tool could not read the page.
3. It applies corrections from Claude agents (Fable 5.2 and Opus 5.5), which read every file after the rules ran and every sentence and item the rules dropped. [`design/reader_removals.csv`](design/reader_removals.csv) lists 27 sentences that go although no rule matches them. [`design/reader_keeps.csv`](design/reader_keeps.csv) lists 73 that stay although a rule matches them, such as an official body's schedule or a poll's numbers. Both lists hold SHA-256 hashes, since the sentences quote news text.
4. It keeps the first copy of each line.

The Opus files run from 32,000 to 58,000 characters and the Sol files from 100,000 to 224,000. `cutoff build` turns the same transcripts and session logs into the same bytes, and `design/files.json` records each file's hash.

## Closed contexts

Each context runs through Subfleet in its isolated mode, on one of the subscription accounts Subfleet draws on (a lane), with a pinned model and a read-only session. The Opus session has no shell. A Sol session keeps one, and the audit fails any context that runs a command. Each context works in a folder whose path names nothing about the study and which holds two short notes and nothing else. [`src/cutoff/audit.py`](src/cutoff/audit.py) reads the records Subfleet keeps and passes a context only when:

- it called no tool (a Sol session's own to-do list counts as none);
- the prompt it received matches its registered prompt, byte for byte up to the line breaks at its end;
- it worked in that folder;
- for Opus, the launch pinned `claude-opus-5-5`, offered only the three file-reading tools in plan mode, and loaded no settings file, memory or MCP server;
- for Opus, the launch held no argument beyond the ones the audit lists, each flag that takes a value once, so nothing added to the system prompt, and its inline setting held environment variables and nothing else;
- for Opus, every message names that model, the usage record lists no other, and Subfleet attests the model that served it;
- for Sol, the launch pinned `gpt-6.1-sol` at ultra effort in an ephemeral, read-only session, with user configuration, rules, project instructions, memories, web search and multi-agent mode off;
- for Sol, the launch held no argument beyond the ones the audit lists, gave no setting twice, and set nothing beyond features switched off and five named values;
- for Sol, the stream holds one thread and one turn, and Subfleet records a clean finish.

The two notes in the folder, `CLAUDE.md` and `AGENTS.md`, each ask the model that reads it to write a code word in the answer. A provider that loads project instructions would show a note to the model, and the audit fails a context whose kept stream carries the code word, in the answer or an earlier message. In rule 8 of every brief, we also ask the model to check what it already holds besides the brief and its evidence file, such as a system prompt, memory or instructions. If any of it mentions the race, data centers or forecasts of the study's questions, the model describes it in `forecaster.prior_context`; otherwise it writes "none". Each note names those topics, so rule 8 covers a note too.

## Which answers count

An answer counts when its context passes the audit and the answer fills its brief's template ([`src/cutoff/response.py`](src/cutoff/response.py)). It needs some text in `prior_context` and a number at every share its brief names: a probability from 0 to 1, or Talarico quantiles that never decrease and stay within 30% to 70%. A context in the alone or told arm restates its scenario as well, and the restated share has to match its own within 0.05 points, with the right winner. We take the answer from the last fenced block that holds the template's questions, and read it as written first. Only an answer that fails gets the two registered repairs, the same in every arm. We drop trailing commas that stop the JSON from parsing, and we drop a key that the template lacks, whether among the questions or among a question's forecasts, when its value holds no JSON object. An answer that needs any other change fails.

An answer whose `prior_context` says anything more than a bare "none", "nothing" or "n/a" waits for a blinded reading. An Opus 5.5 agent sees each distinct text and its key, without its arm, share, model or forecast, and files `clean` or `contaminated` with a reason (`cutoff flags`). The agent files `contaminated` when the text shows that the model saw something besides its prompt that bears on its answer: a note or file in its folder, an instruction from a memory or settings file, or anything about the race, data centers or forecasts of the study's questions. Every other text gets `clean`, as when a model restates its prompt or declines to describe its provider's system prompt. A study prompt holds an evidence file, so a text that describes or quotes that file restates the prompt. A clean answer passes, a contaminated one fails, and a filed decision stands. `review/prior_context.csv` holds each key, decision and reason and names who read the text. The texts stay private, since they can quote the evidence, and `cutoff flags` refuses a reason that quotes its text.

Each attempt at a context runs as one Subfleet job in a fresh conversation. When an answer fails, the context gets a new attempt, at most twice, and when an attempt ends with no answer, as when a lane fails, the context gets another. A context stops, and adds nothing, after three failed answers or five attempts with no answer. When a job ends before any lane starts it, as when Subfleet cancels it in the queue, the attempt never ran and counts toward neither limit. A context that knows of a vote count can say so in `forecaster.notes`; we keep those notes with the context's records, and no check reads them. We also run the analysis without repaired answers and without answers that needed the reading, and report that strict version beside the main one.

## Dry runs and first contexts

Before any context goes out, each model answers one dry-run prompt on one of its lanes ([`src/cutoff/dryrun.py`](src/cutoff/dryrun.py)). In it, we ask for the product of two numbers, and whether anything the model already holds besides the prompt mentions arithmetic or asks for a particular word. The prompt names nothing about the study, and it goes through the same launch, folder and audit as a context. A dry run passes when the audit passes, the product comes out right, the kept stream carries no code word and `prior_context` says "none". A `prior_context` that says more goes to the blinded reading, where anything about arithmetic or a word to write counts as contaminated. A dry run counts only for the Subfleet arguments, prompt and notes it tried, so we run a new one when any of them changes. `cutoff dispatch`, the command that sends contexts, holds each model until its dry run passes. Two failed dry runs, three that end with no answer, or one text filed as contaminated stop that model until we review its records.

Then, until a model's first context passes, its contexts run one at a time. If two answers fail, or three attempts end with no answer, before any passes, that model stops until we review them and send the next one by hand. The model also waits until the blinded reading of its first answer comes back. A fault that every lane shares, one that fails answers, loses attempts or shows in `prior_context`, then costs a few attempts while the model's other contexts wait.

## The analysis

`cutoff analyze` runs [`src/cutoff/analysis.py`](src/cutoff/analysis.py) on the passed answers (`outputs/answers.csv`) and the research runs' own jumps ([`design/reference.json`](design/reference.json)). We express probabilities in points, and a Talarico answer as the mean of the distribution its five quantiles describe ([`src/cutoff/jump.py`](src/cutoff/jump.py)). We run the registered analysis once, when every context has passed or stopped and the replicate rule's record stands. Before then, `cutoff analyze` prints INTERIM at the top of its output and says why.

### Jumps

For each file, model, arm and question, we take the mean answer at each share and fit a least-squares line through the three shares on each side of 50%. The jump measures the gap between the two lines at 50%, Hinojosa's side minus Abbott's, which makes it a fixed weighted sum of the six means:

J = 0.8901 (y50.5 − y49.5) + 0.3681 (y53 − y47) − 0.2582 (y56 − y44)

We multiply each jump by its question's registered direction, so a positive signed jump points the registered way. We registered −1 for ERCOT, where we expect the models to lower their chance when Hinojosa wins, as the research runs did, and +1 for the special session. Talarico's share has no registered direction and keeps its sign.

### The bridge

We can carry the arms' results over to the research runs' jumps only if the evidence files hold what drove those jumps. We test that with a bridge: for each model and question, we take the grid jump of each accepted research run's own file, answered by the same model, and subtract that run's own jump. Each model has six accepted runs: `opus-1`, `opus-3`, `opus-4`, `opus-8`, `opus-9` and `opus-10`, and `sol-1` to `sol-6`. Each question has a margin, the largest difference between two jumps that we treat as none. We set it at 5 points for ERCOT and for the special session, about a third of the two models' average jump on each, and at 0.1 points for Talarico's share. The bridge holds when every accepted run has a grid jump and the mean difference falls within the margin. When a model's bridge fails on a primary question, we leave that model out of the question's pooled differences below and still report its own. A bridge as tight as 0.1 points can fail on noise alone, so we pool both models on Talarico's share whatever its bridge shows, and report the bridge beside the pooled differences. Each bridge difference also takes in what the contexts lack: the web, the ten other questions the research runs answered, and the sentences the screen drops.

### Differences and tests

We compare alone with grid, told with grid, and told with alone. Within each model, we subtract one arm's signed jump from another's for each file, then pool: we average over the models whose bridge holds. A file, model and arm has a jump only when each of the six shares has a passed answer. We treat the file as the unit, since contexts that read one file share its evidence. A file drops out of a difference unless every pooled model has a jump in both arms for it. We average the files' differences, take the standard error from their spread, and use a t distribution with one fewer degree of freedom than files.

We test each difference against zero, two-sided, and for equivalence within its question's margin. For equivalence, we run two one-sided tests at 5%, which pass when the 90% interval falls inside plus or minus the margin. We adjust the two primary differences, alone minus grid on ERCOT and on the special session, by Holm's method for each kind of test. A primary with no pooled result, because no model's bridge holds on it or fewer than two files remain, enters the adjustment with a p-value of 1 and gets no verdict. Each other primary gets one verdict: equivalent if its adjusted equivalence p-value falls below 0.05, different if its adjusted p-value against zero does, and unresolved otherwise. When both adjusted p-values fall below 0.05, the verdict comes out equivalent, because the difference stays inside the margin even though it departs from zero.

### Research against reasoning

Over the twelve accepted runs' files, which both models answer, we tabulate grid jumps by whose research a file holds and which model answers. From that table we split the gap between the models' raw jumps, before the registered direction, into two parts. For the research part, we average, over the two answering models, the mean jump on Sol's files minus the mean jump on Opus's. For the reasoning part, we average, over the twelve files, Sol's jump minus Opus's on the same file.

### What we report

One table holds all three arms with the models pooled, and another gives each model separately. The main analysis sets every verdict, and the strict one sits beside it. When a paper of ours reports the research runs' Texas jumps, we give only those jumps in its abstract if both primary verdicts come out equivalent and both told-minus-grid 90% intervals, unadjusted, fall inside the margin. Otherwise we give the alone arm's pooled jumps from this test beside them in the abstract, or say that the test pooled none where a primary has no pooled result.

## Order and replicates

Contexts run in three waves, each in a seeded random order, so arms and shares interleave in time within each model ([`src/cutoff/design.py`](src/cutoff/design.py): seed 20261110 draws wave 1's files, and 20261111 sets the order).

- Wave 1 runs two files the seed drew: `opus-9`, from the accepted Opus runs, and `sol-4`, from the Sol runs. Both models answer each in every arm at three contexts a share, 156 contexts in all.
- Wave 2 runs the other 14 files at three contexts a share, 1,092 contexts. A model's wave 2 starts once none of its wave 1 contexts runs or waits to run; an answer that awaits the reading does not hold it.
- Wave 3 runs contexts four to six at each share for every file, up to the number the replicate rule picks.

`cutoff tick`, the command a scheduled job runs, applies the replicate rule as soon as wave 1 finishes, including its blinded readings, so no person picks the moment. It measures two spreads for each model and primary question: one over answers within a share in the alone and told arms, and one over the grid contexts' jumps. From them it projects the standard error of each primary difference at three to six contexts a share, and picks the smallest number at which both projected errors fall to 1.648 points or less. We set that threshold by dividing the 5-point margin by the sum of two percentiles: the 95th of a t distribution on 15 degrees of freedom and the 90th of a normal one. At that error, one equivalence test has about an 80% chance of passing when the arms agree on every file. After Holm's adjustment, each primary has about a 72% chance of a verdict of equivalent, and both together about 59% if the two questions' differences vary independently. In projecting, we count the noise within files, leave out any spread of a true difference across them, and assume that both models pool. `cutoff tick` writes its choice to `design/replicates.json` once, and dispatch never sends past it. When no number gets there, or wave 1 holds too few answers to measure a spread, it writes six. `cutoff analyze` recomputes the rule from wave 1's answers and prints its choice beside the recorded one, so an edited record shows. After a model's first context passes, at most four of its contexts run at once. [`outputs/power.md`](outputs/power.md) gives the planning table.

## Limits

- Equivalence within 0.1 points on Talarico's share needs a standard error below 0.057 points, and an 80% chance of it needs 0.033. Even at six contexts a share and with no spread across files, an error below 0.057 points needs answers within a share to spread less than 0.4 points, if a grid context's six answers vary independently. We therefore give Talarico's share no verdict and report its differences with their intervals.
- The pooled verdict can hide effects that differ by model, and each model's own differences carry no verdict. The 5-point margin comes to 60% of Sol's ERCOT jump in the research runs, so a verdict of equivalent leaves room for the format to account for more than half of that jump.
- We set the margin from the research runs' own jumps and have no outside basis for it.
- In every arm, the contexts read evidence that a research run gathered while it answered all six shares at once. We vary only how we ask a closed context, so we cannot learn what a research run asked about one share would gather or conclude.
- The alone and told arms differ from the grid in more than the number of shares. In their briefs, we name the winner, ask how the scenario bears on each forecast, and ask the model to restate its share and the winner.
- An ephemeral Codex session in Subfleet's isolated mode leaves no record of the model that served it, so for Sol we rely on the launch pin, while Subfleet attests the model that served each Opus context.
- Neither provider's stream keeps the model's reasoning text as we launch it. A context that named the code word only in its reasoning would pass the code-word check, and the launch checks alone would stand against a loaded note.
- We decide which models pool on a primary from the same grid contexts that enter the differences. When noise pulls a model's grid jumps toward its research runs' jumps, the model passes its bridge more easily. The same noise enters alone minus grid with the opposite sign, so it can shift the pooled difference slightly, against the direction of that pull.
- Sol's files hold only the main thread's text and run about three times as long as Opus's, so the research part of the split between research and reasoning carries the files' length and the sub-agent text they leave out.
- When the screen drops an item whole for its odds, it drops the facts in it too. The agents that checked the screen found three: two sets of poll numbers and how long Republicans have held the governorship.
- Each dry run and each model's first contexts try one lane at a time, so a fault that only some lanes carry can reach later contexts, where the audit fails them one by one.
- Models produced every forecast and jump in this study under stated scenarios. A jump measures how their forecasts change across 50%, not an effect anyone observed.

## Files

This repository holds the briefs, the design tables in [`design/`](design/), the code, the tests and the outputs. The evidence files, the prompts, the screen logs, the sentences behind the agents' two lists, every context's records and the `prior_context` texts quote news text, so they stay in a private folder outside the repository (`CUTOFF_PRIVATE`). The design tables record the hashes of the evidence files, the prompts and the sentences on the agents' lists.

The six Sol files need the private session logs. To rebuild the ten Opus evidence files and their prompts and check each hash, clone the [Texas repository](https://github.com/MaxGhenis/texas-governor-data-center-forecasts) to `~/texas-governor-data-center-forecasts` (or point `CUTOFF_PUBLIC_TEXAS` at it) and run:

```bash
uv sync --extra dev
```

```bash
.venv/bin/cutoff build --check
```

```bash
.venv/bin/pytest -n 4
```

`uv.lock` pins the versions we ran. [`src/cutoff/cli.py`](src/cutoff/cli.py) lists the other commands: `status`, `dryrun`, `dispatch`, `collect`, `tick`, `flags`, `replicates`, `analyze`, `registration` and `power`. Run on a schedule, `tick` collects finished contexts, sends any dry run that falls due, applies the replicate rule once wave 1 has finished, then dispatches.

## The registration

`cutoff registration --write` wrote `prereg/registration/SHA256SUMS`, which lists the SHA-256 of every file git tracks among the README, the briefs, `design/`, `outputs/power.md`, the code in `src/` and `scripts/`, the tests, `pyproject.toml`, `uv.lock` and the CI workflow. OpenTimestamps anchors that list in Bitcoin, and `prereg/registration/SHA256SUMS.ots` holds the proof. The proof opens with the list's own SHA-256, and every check here fails a list that no longer matches it. The replicate rule's record, `design/replicates.json`, comes after the stamp. `cutoff dispatch` refuses to send a context unless the list and its proof stand together and the briefs and the four design tables that name the stimulus (`prompts.csv`, `contexts.csv`, `files.json` and `sandbox.json`) still match the list. It also checks each prompt file against its hash in `design/prompts.csv`, and refuses while the contexts' folder holds anything besides the two notes.

After the stamp, we record any change to a listed file, and any file we add to those folders, as a dated deviation under `prereg/`. Each deviation names the file and the first twelve characters of its new SHA-256, or says that we removed it. `cutoff analyze` and the replicate rule run whether or not a change has its record, and their output lists every changed or added file beside the record that names it, or says that none does. `cutoff registration --check`, which CI runs, fails while any change lacks a record. Anyone can check every file against the list from the repository's root:

```bash
shasum -a 256 -c prereg/registration/SHA256SUMS
```

After a deviation, that command prints FAILED for the changed file, and `cutoff registration` shows the record that names it. To check the list against its proof without a Bitcoin node:

```bash
uvx --from opentimestamps-client ots --no-bitcoin verify prereg/registration/SHA256SUMS.ots
```

That command checks that the proof belongs to the list. Once Bitcoin has confirmed the stamp, we commit the upgraded proof, and the command then prints a Bitcoin block's height and Merkle root. The stamp holds if any block explorer shows that root for that block, and the block's time dates the list. With a Bitcoin node it can reach, `ots verify` makes the same check itself.

MIT license.
