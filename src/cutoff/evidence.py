"""Compile each evidence file from what a sealed Texas run gathered before polls closed.

An evidence file holds only text that the run's web tools returned: each search's results and each
page's text or extract, in the order the run read them. It holds nothing the run wrote itself: no
queries, no fetch prompts, no reasoning, no sub-agent reports and no answer.

- **Opus runs** (`runs/opus-N/transcript.jsonl` in the public Texas repository): the result of every
  `WebSearch` and `WebFetch` call. A search result keeps its list of links and the search tool's
  summary; the line that repeats the run's query goes. A fetch keeps the extract and its address; the
  run's fetch prompt goes.
- **Sol runs** (the main thread's session log in the private Texas repository): the output of every
  `exec` call whose script calls `tools.web__run`, split into the pages and search results it
  returned. Values that a script computed itself (counts, lists it built) go; only strings the web
  tool returned stay. Each Sol run also spawned three sub-agents. Their own reading came to 2.4 to 5.9
  times the main thread's, 485,000 to 686,000 characters a run after the steps below
  (`design/files.json` gives each run's count), and adding it would more than triple what the study's
  contexts read. So a Sol file holds the main thread's reading only: the sub-agents' reading stays
  out, and so do the reports they wrote back, which are the run's own text.

Then, in order:

1. **Clean.** Drop the tools' bookkeeping (citation markers, line numbers, crawl metadata, script
   banners, local file paths, error and no-match notices, truncation marks, form-control tags),
   navigation lines that hold only links, inline HTML tags, and lines with no letter or digit. Keep
   link text.
2. **Screen.** Split each line into sentences and drop every sentence that matches a rule in
   `SCREEN`: prediction markets and odds, forecasts and ratings of a race, chances and probabilities,
   words of expectation, statements of what the election's result would do, and the search or reading
   tool speaking back to the session that called it. A search hit (a title with its address) counts as one sentence,
   and every rule also reads the text with hyphens, underscores and slashes turned to spaces, so a
   headline inside an address counts. A statement of what a candidate or campaign says it will do
   stays, since it reports a position held before the vote. Each run wrote its searches and fetch
   prompts with the questions in mind, so the tools' summaries can carry forecasts and effects the
   sources never stated; the screen removes those too. An item goes whole when a quarter or more of
   its sentences (and at least two) match the `markets` rule: it came from a search about betting
   odds, and the tool's summary speaks of prices throughout. An extract goes whole when its first
   line says the reading tool could not read the page: what follows lists what the run asked for.
3. **Readers' corrections.** Readers went through every file after the rules ran, and through
   every sentence the rules dropped (README, "The evidence files"). A sentence whose SHA-256
   `design/reader_removals.csv` lists goes although no rule matched it; a sentence that
   `design/reader_keeps.csv` lists stays although a rule matched it (an official body's own schedule,
   a fiscal or load projection, a poll number). The lists hold hashes, since the sentences quote news
   text. A kept sentence still counts toward the betting-odds share of its item.
4. **Deduplicate.** Keep the first copy of each line.

No step shortens an item: a file holds every line that survives the four steps. Everything here is deterministic: the same sealed logs give the same bytes, and `design/files.json`
records each file's SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

HEADER = (
    "Each item below is something the research session's web tools returned on 2026-11-03, before polls "
    "closed, in the order it read them: search results and the text or extract of pages it opened. A "
    "script removed navigation text, duplicate lines and some passages. Items can conflict, and some are "
    "out of date."
)


@dataclass
class Item:
    label: str  # "Search results", "Extract", "Page" or "Search result"
    title: str  # what follows the label in the item's header: a page's title and address
    lines: list[str] = field(default_factory=list)
    order: tuple = ()

    def header(self) -> str:
        return f"{self.label}: {self.title}" if self.title else self.label


# ---------------------------------------------------------------------------------------------- screen

_ACTORS = (
    r"(?:she|he|hinojosa|abbott|talarico|paxton|democrats?|republicans?|the\s+democrat|the\s+republican|"
    r"a\s+democrat|a\s+republican|the\s+challenger|the\s+incumbent|either\s+candidate)"
)
_WINLOSE = (
    r"(?:wins?|won|winning|is\s+elected|were\s+elected|gets\s+elected|becomes\s+governor|takes\s+office|"
    r"unseats|beats|defeats|loses|lost|prevails|flips)"
)
_CANDIDATES = r"(?:hinojosa|abbott|talarico|paxton)"

# The registered screen. A sentence goes if any pattern matches it (case-insensitive). Each pattern reads
# the sentence twice: as it stands, and with hyphens, underscores and slashes turned to spaces, so a
# headline inside an address counts. Before either reading, two phrases are masked: "likely voter(s)"
# and "likely electorate" (a poll's sample, not an expectation), and the name of the forum
# reddit.com/r/fivethirtyeight (where people post polls; the forecaster FiveThirtyEight still counts).
# The first rule that matches names the reason in the build's counts.
SCREEN: dict[str, list[str]] = {
    "markets": [
        r"\b(?:polymarket|kalshi|predictit|prediction\s*hunt|predicthunt|defi\s*rate|betting|bettors?|"
        r"bookmakers?|sportsbooks?|oddsmakers?|wagers?|wagering)\b",
        r"\bprediction\s+markets?\b",
        r"\b\d+(?:\.\d+)?\s?¢",
        r"\b(?:over|under|mis)priced\b",
        r"\b(?:live|market|contract)\s+prices?\b",
        r"\bliquidity\b",
        rf"\b{_CANDIDATES}\s+at\s+\d+(?:\.\d+)?\s?%\s+(?:for|to\s+win)\b",
    ],
    "forecasts": [
        r"\b(?:forecast\w*|predict\w*|prognos\w*|projections?|race\s+ratings?|toss[- ]?ups?|crystal\s+ball|"
        r"cook\s+political|sabato|inside\s+elections|decision\s+desk|fivethirtyeight|silver\s+bulletin|"
        r"split\s+ticket)\b",
        r"\b(?:leans?|likely|safe|tilts?)\s+(?:republican|democratic|democrat|gop)\b",
        # A race rated in an idiom.
        r"\b(?:too\s+close\s+to\s+call|dead[- ]heat|neck[- ]and[- ]neck|photo[- ]finish|coin[- ]flip|"
        r"down\s+to\s+the\s+wire|nail[- ]?bit\w+|long[- ]?shot|uphill|front[- ]?runner|glimmer\s+of\s+hope|"
        r"dogfights?|polling\s+blow|cautiously\s+optimistic)\b",
        r"\b(?:blue|red)\s+wave\b",
        r"\b(?:tight|close|competitive|tightening|tightened)\s+(?:race|contest|election|battle)\b",
        r"\bunexpectedly\s+(?:tough|close|strong|competitive)\b",
        r"\b(?:an|the|major|stunning|historic)\s+upset\b|\bupset\s+(?:win|victory|bid)\b",
        # Who can, could or will win or lose.
        r"\b(?:can|could|may|might|will|would|is\s+going\s+to|are\s+going\s+to|about\s+to)\s+"
        r"(?:still\s+|yet\s+|easily\s+|narrowly\s+)?(?:win|lose(?!\s+out\b)|prevail|flip|unseat|oust|elect)\b",
        r"\bcould\s+(?:see|hinge|turn\s+on|come\s+down\s+to|go\s+either\s+way|swing)\b",
        r"\bpolls?\b[^.\n]{0,40}\bpoint(?:s|ing|ed)?\s+to\b",
        r"\b(?:democratic|republican|gop|democrats['’]?|republicans['’]?)\s+hopes\b",
        r"\b(?:good|bad|warning|worrying|encouraging|ominous)\s+signs?\b",
        rf"\b{_CANDIDATES}\s+(?:is|are|was)\s+(?:struggling|in\s+trouble|in\s+danger|vulnerable|surging|fading)\b",
        r"\bshould\s+(?:texas\s+)?(?:republicans|democrats)\s+be\s+worried\b",
        r"\blead\b[^.;:]{0,40}\b(?:safe|safer|secure|comfortable|insurmountable|precarious)\b",
    ],
    "chances": [
        r"\b(?:chances?|probabilit\w*|probable|improbable|likelihood|odds|favou?rites?|underdogs?)\b",
    ],
    "expectations": [
        r"\b(?:likely|unlikely|expect\w*|anticipat\w*|doubt\w*|poised\s+(?:to|for)|on\s+track\s+to|"
        r"almost\s+certain|all\s+but\s+certain|virtually\s+certain|certain\s+to|bound\s+to)\b",
        r"\b(?:analysts?|experts?|observers?|pundits?|strategists?)\s+(?:\w+\s+){0,2}(?:believe|think|foresee|see)s?\b",
    ],
    "effects": [
        rf"\bif\s+{_ACTORS}\b[^.;:]{{0,60}}?\b{_WINLOSE}\b",
        rf"\b(?:{_CANDIDATES}|democratic|republican|gop)(?:['’]s)?\s+(?:win|victory|upset|administration|"
        r"governorship|sweep|takeover|loss|defeat)\b",
        r"\bunder\s+(?:a|an)\s+(?:hinojosa|abbott|democratic|republican|new)\s+(?:governor|administration)\b",
        r"\b(?:gov\.?|governor)\s+hinojosa\b",
        r"\b(?:election|race|vote|outcome|results?)\b[^.;:]{0,60}\b(?:would|will|could|may|might)\s+"
        r"(?:determine|decide|shape|affect|mean|bring|end|lift|keep|extend|change)\b",
        r"\bonce\s+elected\b",
    ],
    # The search tool or the page-reading tool speaking back to the session that called it: such a
    # sentence repeats the session's question. (A tool's "I found" sentences stay: they carry the facts.)
    "tool_voice": [
        r"\byour\s+(?:query|question|request|prompt|search|instructions?)\b",
        r"\byou\s+(?:asked|provided|requested|mentioned|paste|could\s+paste|can\s+use)\b|\byou(?:['’]re|\s+are)\s+asking\b",
        r"\brequested\s+information\b|\bcontent\s+(?:you\s+)?provided\b",
    ],
}
MARKET_ITEM_SHARE = 0.25  # an item goes whole when this share of its sentences match the markets rule
# A page-reading tool that could not read its page answers with what it was asked for, and no content.
FAILED_EXTRACT = re.compile(r"\b(?:content\s+(?:you\s+)?provided|requested\s+information)\b", re.I)
_COMPILED = {rule: [re.compile(p, re.I) for p in pats] for rule, pats in SCREEN.items()}
_LIKELY_VOTERS = re.compile(r"\blikely[\s_-]+(?:texas[\s_-]+)?(?:voters?|electorate)\b", re.I)
_FORUM = re.compile(r"\br/fivethirtyeight\b", re.I)
# A line of an interview transcript ("HOST NAME: ...") speaks to the guest, not to the session:
# the tool_voice rule skips it.
_SPEAKER = re.compile(r"^\W*[A-Z][A-Z.'’ -]{2,40}:\s")


def _mask(text: str) -> str:
    return _LIKELY_VOTERS.sub("LV", _FORUM.sub("r/forum", text))

# A statement of what a candidate or campaign says it will do is a position, not an effect: the effect
# rules skip a sentence whose subject is a candidate, a campaign or a pronoun for one, followed within two
# words by a verb of saying or pledging, or that names a candidate's plan, platform or pledge.
_SPEECH = (
    r"(?:said|says|saying|pledged|pledges|promised|promises|vowed|vows|plans|planned|proposed|proposes|"
    r"called\s+for|calls\s+for|announced|announces|told|tells|wrote|writes|unveiled|wants|stated|states|"
    r"argued|argues|insisted|insists|committed|commits|would\s+call|will\s+call)"
)
_POSITION = [
    re.compile(
        rf"\b(?:{_CANDIDATES}|(?:her|his|the)\s+campaign|she|he)\b,?\s+(?:who\s+)?(?:\w+\s+){{0,2}}{_SPEECH}\b",
        re.I,
    ),
    re.compile(
        rf"\b{_CANDIDATES}['’]s\s+(?:\w+\s+)?(?:plan|platform|pledge|proposal|promise|agenda|campaign)\b", re.I
    ),
]

_ABBREVIATIONS = {
    "gov", "sen", "rep", "lt", "dr", "mr", "mrs", "ms", "st", "jr", "sr", "inc", "co", "corp", "no", "vs",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "e.g", "i.e",
    "u.s", "a.m", "p.m", "approx", "est", "dept", "gen", "atty",
}
_BOUNDARY = re.compile(r"(?<=[.!?])([\"”’)\]]*)\s+(?=[A-Z0-9\"“(\[*$])")


def sentences(line: str) -> list[str]:
    """Split a line at sentence ends, but not after a listed abbreviation, a single capital or a run
    of initials ("J.D."). A closing quotation mark or bracket stays with the sentence it closes."""
    out, start = [], 0
    for m in _BOUNDARY.finditer(line):
        end = m.end(1)
        before = line[start:end].rstrip("\"”’)]")
        token = re.search(r"([A-Za-z.]+)\.$", before)
        word = token.group(1).lower() if token else ""
        if word in _ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.)*[a-z]", word):
            continue
        out.append(line[start:end].strip())
        start = m.end()
    out.append(line[start:].strip())
    return [s for s in out if s]


_SLUG = re.compile(r"[-_/]+")
_HIT = re.compile(r"^- .+\(https?://\S+\)$")  # a search hit: "- title (address)"


def screen_reason(sentence: str) -> str | None:
    """The first screen rule a sentence matches, or None if it stays."""
    text = _mask(sentence)
    spaced = _SLUG.sub(" ", text)
    for rule, patterns in _COMPILED.items():
        if any(p.search(text) or p.search(spaced) for p in patterns):
            if rule == "effects" and any(p.search(text) for p in _POSITION):
                continue
            if rule == "tool_voice" and _SPEAKER.match(sentence):
                continue
            return rule
    return None


def units(line: str) -> list[str]:
    """What the screen judges one at a time: a search hit whole, any other line's sentences."""
    return [line] if _HIT.match(line) else sentences(line)


def sentence_key(sentence: str) -> str:
    """The key `design/removals.csv` files a sentence under: the SHA-256 of its text with white space
    collapsed."""
    return hashlib.sha256(_norm(sentence).encode()).hexdigest()


@dataclass(frozen=True)
class Readers:
    """The readers' corrections: keys (`sentence_key`) of sentences to drop although no rule matches,
    and of sentences to keep although one does. A key in both goes."""

    removals: frozenset = frozenset()
    keeps: frozenset = frozenset()


NO_READERS = Readers()


def verdict(sentence: str, readers: Readers = NO_READERS) -> str | None:
    """Why a sentence goes, or None if it stays: a screen rule's name, or "reader"; a sentence the
    readers kept stays, and counts under "reader_kept" in the build."""
    key = sentence_key(sentence) if (readers.removals or readers.keeps) else ""
    if key in readers.removals:
        return "reader"
    reason = screen_reason(sentence)
    if reason is not None and key in readers.keeps:
        return None
    return reason


def screen_line(line: str, counts: dict, log: list | None = None, readers: Readers = NO_READERS) -> str:
    """The line without its screened sentences ("" if none stays); `counts` tallies what went, and
    `log`, if given, collects (rule, sentence) for each."""
    kept = []
    for s in units(line):
        reason = verdict(s, readers)
        if reason is None and readers.keeps and screen_reason(s) is not None:
            counts["reader_kept"] = counts.get("reader_kept", 0) + 1
        if reason is None:
            kept.append(s)
        else:
            counts[reason] = counts.get(reason, 0) + 1
            counts["chars_screened"] = counts.get("chars_screened", 0) + len(s)
            if log is not None:
                log.append((reason, s))
    return " ".join(kept)


# ----------------------------------------------------------------------------------------------- clean

_CITE = re.compile(".*?")
_LINENO = re.compile(r"^L\d+(?:@P\d+(?:-\d+)?)?:\s?")
_LINK = re.compile(r"【\d+†([^†】]*)(?:†[^】]*)?】")
_NAV_ONLY = re.compile(r"^\s*(?:[*\-•+]\s*)?(?:【\d+†[^】]*】\s*)+$")
_LOCAL_PATH = re.compile(r"(?:/Users/|/private/|/tmp/|~/)\S*")
_HAS_WORD = re.compile(r"[A-Za-z0-9]")
_RULE_LINE = re.compile(r"^[\s*_\-|:=#>]*$")
_NOTICE = re.compile(
    r"^(?:No matching text found for |The server returned HTTP \d|The response body was not retrieved)|"
    r"\d+ tokens truncated"
)
_UI_TAG = re.compile(r"\[(?:Button|Input|Image|Checkbox|Select|Radio)\b[^\]]*\]", re.I)
_HTML_TAG = re.compile(
    r"</?(?:a|b|i|u|em|strong|span|br|p|div|li|ul|ol|td|tr|th|table|thead|tbody|h[1-6]|sup|sub|img|figure|"
    r"figcaption|blockquote|section|article|script|style)\b[^>]{0,400}>",
    re.I,
)


def clean_line(line: str) -> str:
    line = _CITE.sub("", line)
    line = _LINENO.sub("", line)
    if _NAV_ONLY.match(line):
        return ""
    line = _LINK.sub(lambda m: m.group(1), line)
    line = _HTML_TAG.sub(" ", _UI_TAG.sub(" ", line))
    line = line.replace("\xa0", " ")
    line = re.sub(r"[ \t]+", " ", line).strip()
    if _LOCAL_PATH.search(line) or _NOTICE.search(line):
        return ""
    if not _HAS_WORD.search(line) or _RULE_LINE.match(line) or line in {"* * *", "×"}:
        return ""
    return line


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


# ------------------------------------------------------------------------------------------------ opus

_OPUS_BOILERPLATE = re.compile(
    r"^(?:Web search results for query:|REMINDER: You MUST include the sources above|\[Binary content)", re.I
)


def _tool_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def opus_items(transcript: Path) -> list[Item]:
    """Every WebSearch and WebFetch result in an Opus run's transcript, in the order it arrived."""
    uses: dict[str, tuple[str, dict]] = {}
    items: list[Item] = []
    for n, raw in enumerate(transcript.read_text().splitlines()):
        e = json.loads(raw)
        if e.get("type") == "assistant":
            for b in e["message"].get("content", []):
                if b.get("type") == "tool_use":
                    uses[b["id"]] = (b["name"], b.get("input") or {})
        elif e.get("type") == "user" and isinstance(e["message"].get("content"), list):
            for b in e["message"]["content"]:
                if b.get("type") != "tool_result" or b.get("is_error"):
                    continue
                name, inp = uses.get(b.get("tool_use_id"), (None, {}))
                text = _tool_text(b.get("content"))
                if name == "WebSearch":
                    items.append(Item("Search results", "", _opus_search_lines(text), (n,)))
                elif name == "WebFetch":
                    url = str(inp.get("url", ""))
                    lines = [ln for ln in text.splitlines() if not _OPUS_BOILERPLATE.match(ln.strip())]
                    items.append(Item("Extract", url, lines, (n,)))
    return items


def _opus_search_lines(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("Links: ["):
            try:
                links = json.loads(s[len("Links: ") :])
            except json.JSONDecodeError:
                continue
            out += [f"- {x.get('title', '').strip()} ({x.get('url', '').strip()})" for x in links if isinstance(x, dict)]
        elif not _OPUS_BOILERPLATE.match(s):
            out.append(ln)
    return out


# ------------------------------------------------------------------------------------------------- sol

_EXEC_BANNER = re.compile(
    r"^(?:Script completed|Wall time [\d.]+ \w+|Output:|Warning: truncated output.*|Total output lines: \d+)$"
)
_SEPARATOR = re.compile(r"-{20,}")
_TITLE = re.compile(r"^(.*?)\s*\((https?://[^\s)]+[^\s]*)\)\s*$")
_META_FIELD = re.compile(
    r"(?:\[wordlim: \d+\]\s*)|(?:Crawled: [^;]*;\s*)|(?:Content type: [^;]*;\s*)|(?:Number of pages: \d+;\s*)|"
    r"(?:Source: \w+\(.*?\);\s*)|(?:Total lines: \d+\s*)"
)
_PUBLISHED = re.compile(r"(?:Published|Updated): ([^;]*);\s*")
_ERROR = re.compile(r"Internal Error \(\)|is not accessible via this tool|^Failed to fetch|Error: ", re.M)


def _exec_output_text(payload: dict) -> str:
    out = payload.get("output")
    if isinstance(out, list):
        return "".join(x.get("text", "") for x in out if isinstance(x, dict))
    return str(out or "")


def tool_strings(output: str) -> list[str]:
    """The strings the web tool returned, from one exec call's printed output.

    The output starts with a banner ("Script completed", the wall time, "Output:", a truncation note).
    A script that failed returns nothing. Each JSON value a later line starts with is a value the
    script printed: a settled promise ({status, value} or {i, result: {status, value}}), a list of
    strings or a string keeps its strings; any other object holds values the script computed and
    goes. Lines that start with no JSON value are tool text, which runs of consecutive lines keep
    together.
    """
    lines = output.split("\n")
    if not lines or lines[0].strip() != "Script completed":
        return []
    chunks: list[str] = []
    plain: list[str] = []

    def flush():
        if plain:
            chunks.append("\n".join(plain))
            plain.clear()

    for ln in lines:
        if _EXEC_BANNER.match(ln.strip()):
            continue
        values, rest = _peel(ln.strip())
        if not values:
            plain.append(ln)
            continue
        flush()
        for v in values:
            chunks += _strings_from(v)
        if rest:
            plain.append(rest)
    flush()
    return [c for c in chunks if c.strip()]


_DECODER = json.JSONDecoder()


def _peel(s: str) -> tuple[list, str]:
    """The JSON values a printed line starts with, and what follows them. A script can print several
    values on one line, or a value with tool text after it. A line that is one JSON string is a value;
    a line that merely starts with a quotation mark is text."""
    if s[:1] == '"':
        try:
            return [json.loads(s)], ""
        except json.JSONDecodeError:
            return [], s
    values, rest = [], s
    while rest[:1] in ("{", "["):
        try:
            v, end = _DECODER.raw_decode(rest)
        except json.JSONDecodeError:
            break
        values.append(v)
        rest = rest[end:].lstrip()
    return values, rest


def _strings_from(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return ["\n".join(x for x in v if isinstance(x, str))] if all(isinstance(x, str) for x in v) else []
    if isinstance(v, dict):
        if isinstance(v.get("value"), str) and v.get("status", "fulfilled") == "fulfilled":
            return [v["value"]]
        if isinstance(v.get("result"), dict):
            return _strings_from(v["result"])
    return []


def split_results(text: str, order: tuple) -> list[Item]:
    """The pages and search results in one tool string, which separates them with lines of dashes."""
    items = []
    for k, raw in enumerate(_SEPARATOR.split(text)):
        lines = raw.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines or _ERROR.search("\n".join(lines[:3])):
            continue
        title, url, published = "", "", ""
        m = _TITLE.match(_CITE.sub("", lines[0]).strip())
        if m:
            title, url = m.group(1).strip(), m.group(2)
            lines = lines[1:]
        kind, content = "search result", []
        for ln in lines:
            bare = _CITE.sub("", ln)
            if "[wordlim:" in bare:
                if "Source: " in bare or "Total lines:" in bare:
                    kind = "page"
                pub = _PUBLISHED.search(bare)
                published = published or (pub.group(1).strip() if pub else "")
                rest = _PUBLISHED.sub("", _META_FIELD.sub("", bare)).strip()
                if rest:
                    content.append(rest)
            else:
                content.append(ln)
        label = "Page" if kind == "page" else "Search result"
        head = f"{title} ({url})" if url else ""
        if published:
            head += f", published {published}"
        items.append(Item(label, head.strip(" ,"), content, order + (k,)))
    return items


def main_thread(session_logs: list[Path]) -> Path:
    """The run's own thread: the one session log whose metadata says a user, not a parent thread,
    started it."""
    mains = []
    for path in session_logs:
        with path.open() as f:
            first = json.loads(f.readline())
        if first.get("type") == "session_meta" and (first.get("payload") or {}).get("thread_source") == "user":
            mains.append(path)
    if len(mains) != 1:
        raise ValueError(f"expected one main thread, found {len(mains)} in {[p.name for p in session_logs]}")
    return mains[0]


def sol_items(session_logs: list[Path]) -> list[Item]:
    """Every web result in the given session logs, merged in time order."""
    events = []
    for t, path in enumerate(session_logs):
        calls: dict[str, dict] = {}
        for n, raw in enumerate(path.read_text().splitlines()):
            e = json.loads(raw)
            p = e.get("payload") or {}
            if e.get("type") != "response_item":
                continue
            if p.get("type") == "custom_tool_call":
                calls[p.get("call_id")] = p
            elif p.get("type") == "custom_tool_call_output":
                call = calls.get(p.get("call_id")) or {}
                if call.get("name") == "exec" and "web__run" in str(call.get("input", "")):
                    events.append((e.get("timestamp", ""), t, n, _exec_output_text(p)))
    events.sort()
    items: list[Item] = []
    for ts, t, n, text in events:
        for s, string in enumerate(tool_strings(text)):
            items += split_results(string, (ts, t, n, s))
    return items


# --------------------------------------------------------------------------------------------- compile


def market_item(lines: list[str]) -> bool:
    """Whether an item's cleaned lines came from a search about betting odds: a quarter or more of its
    sentences, and at least two, match the markets rule."""
    us = [u for ln in lines for u in units(ln)]
    hits = sum(screen_reason(u) == "markets" for u in us)
    return hits >= 2 and hits >= MARKET_ITEM_SHARE * len(us)


def whole_item_reason(label: str, cleaned: list[str]) -> str | None:
    """Why an item goes whole ("market_item" or "failed_extract"), or None."""
    if market_item(cleaned):
        return "market_item"
    if label == "Extract" and cleaned and FAILED_EXTRACT.search(cleaned[0]):
        return "failed_extract"
    return None


def process(items: list[Item], log: list | None = None, readers: Readers = NO_READERS) -> tuple[list[Item], dict]:
    """Clean, screen and deduplicate the items; return the survivors and the counts."""
    counts: dict = {"items_in": len(items)}
    seen: set[str] = set()
    out: list[Item] = []
    for it in items:
        title = it.title
        if title and verdict(title, readers) is not None:
            counts["titles_screened"] = counts.get("titles_screened", 0) + 1
            title = ""
        cleaned = [c for c in (clean_line(ln) for ln in it.lines) if c]
        whole = whole_item_reason(it.label, cleaned)
        if whole:
            counts[whole + "s"] = counts.get(whole + "s", 0) + 1
            counts["chars_screened"] = counts.get("chars_screened", 0) + sum(len(c) for c in cleaned)
            if log is not None:
                log += [(whole, u) for c in cleaned for u in units(c)]
            continue
        lines = []
        for c in cleaned:
            c = screen_line(c, counts, log, readers)
            if not c or not _HAS_WORD.search(c):
                continue
            key = _norm(c)
            if key in seen:
                counts["duplicate_lines"] = counts.get("duplicate_lines", 0) + 1
                continue
            seen.add(key)
            lines.append(c)
        if lines:
            out.append(Item(it.label, title, lines, it.order))
    counts["items_kept"] = len(out)
    return out, counts


def trace(items: list[Item], readers: Readers = NO_READERS) -> tuple[list[str], list[tuple[str, str]]]:
    """Every unit the screen judged, by fate: the ones that stay (titles included), and the ones that
    go, each with its reason. `scripts/reader_lists.py` matches the readers' findings against these."""
    stay: list[str] = []
    go: list[tuple[str, str]] = []
    for it in items:
        if it.title:
            reason = verdict(it.title, readers)
            (stay.append(it.title) if reason is None else go.append((reason, it.title)))
        cleaned = [c for c in (clean_line(ln) for ln in it.lines) if c]
        whole = whole_item_reason(it.label, cleaned)
        if whole:
            go += [(whole, u) for c in cleaned for u in units(c)]
            continue
        for c in cleaned:
            for u in units(c):
                reason = verdict(u, readers)
                (stay.append(u) if reason is None else go.append((reason, u)))
    return stay, go


def render(items: list[Item]) -> str:
    """The evidence file: the header, then each item, numbered, with its lines."""
    blocks = [HEADER, ""]
    for k, it in enumerate(items, 1):
        blocks.append(f"[{k}] {it.header()}")
        blocks += it.lines
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def compile_evidence(items: list[Item], log: list | None = None, readers: Readers = NO_READERS) -> tuple[str, dict]:
    """The evidence file and its counts; `log`, if given, collects each screened sentence."""
    kept, counts = process(items, log, readers)
    text = render(kept)
    counts.update(chars=len(text), sha256=hashlib.sha256(text.encode()).hexdigest())
    return text, counts
