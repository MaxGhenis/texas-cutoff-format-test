"""The evidence screen and the steps around it: sentence splitting, cleaning, the rules, the readers'
corrections, whole-item drops, deduplication and the rendered file. Every input here is MOCK text."""

from __future__ import annotations

import json
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cutoff import evidence as E
from cutoff.evidence import Item, Readers


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------------------------------ sentences


@pytest.mark.parametrize(
    "line, want",
    [
        ('He said "Go." Then he left.', ['He said "Go."', "Then he left."]),
        ("(See the table.) Next came the vote.", ["(See the table.)", "Next came the vote."]),
        ("Rep. J.Q. Public spoke today. He left.", ["Rep. J.Q. Public spoke today.", "He left."]),
        ("Gov. Abbott spoke. The U.S. economy grew.", ["Gov. Abbott spoke.", "The U.S. economy grew."]),
        ("A. Lincoln won. B won.", ["A. Lincoln won.", "B won."]),
        ("It rose 3.5 percent. Then it fell!", ["It rose 3.5 percent.", "Then it fell!"]),
        ("Is it? Yes.", ["Is it?", "Yes."]),
        ("no capital after. so no split.", ["no capital after. so no split."]),
    ],
)
def test_sentences_split_where_a_reader_would(line, want):
    assert E.sentences(line) == want


words = st.sampled_from(["Abbott", "said", "the", "Gov.", "J.D.", "U.S.", "data", "centers", "3.5", "ERCOT", "(note)",
                         '"Go."', "it.", "yes!", "why?", "[1]", "x", "A.", "”", "pause"])  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(st.lists(words, min_size=1, max_size=25), st.lists(st.sampled_from([" ", "  ", "\t"]), min_size=25, max_size=25))
def test_splitting_loses_no_text(ws, gaps):
    line = "".join(w + g for w, g in zip(ws, gaps))
    assert norm(" ".join(E.sentences(line))) == norm(line)


def test_a_search_hit_is_one_unit_and_other_lines_are_sentences():
    hit = "- Abbott wins. Odds shift (https://example.com/MOCK)"
    assert E.units(hit) == [hit]
    assert E.units("One. Two.") == ["One.", "Two."]


# ------------------------------------------------------------------------------------------- cleaning


@pytest.mark.parametrize(
    "raw, want",
    [
        ("L12: The pause began in June.", "The pause began in June."),
        ("L7@P2-3: Text.", "Text."),
        ("No matching text found for \"MOCK\"", ""),
        ("The server returned HTTP 403", ""),
        ("<p>ERCOT <a href=\"https://x.org\">paused</a> approvals.</p>", "ERCOT paused approvals."),
        ("[Button: Subscribe] Read more", "Read more"),
        ("* * *", ""),
        ("----", ""),
        ("see /Users/someone/file.txt", ""),
        ("A\xa0B", "A B"),
    ],
)
def test_cleaning(raw, want):
    assert E.clean_line(raw) == want


def test_peel_reads_several_json_values_and_keeps_the_text_after_them():
    values, rest = E._peel('{"status": "fulfilled", "value": "A"} ["B", "C"] trailing words')
    assert values == [{"status": "fulfilled", "value": "A"}, ["B", "C"]]
    assert rest == "trailing words"
    assert E._peel('"just a string"') == (["just a string"], "")
    assert E._peel('"starts with a quote but is text') == ([], '"starts with a quote but is text')


def test_tool_strings_keep_returned_strings_and_drop_computed_values():
    out = "\n".join(
        [
            "Script completed",
            json.dumps({"status": "fulfilled", "value": "MOCK page text."}),
            json.dumps({"i": 1, "result": {"status": "fulfilled", "value": "MOCK second page."}}),
            json.dumps({"share": 0.52, "note": "a value the script computed"}),
            json.dumps(["MOCK hit one", "MOCK hit two"]),
            "plain tool text",
        ]
    )
    assert E.tool_strings(out) == ["MOCK page text.", "MOCK second page.", "MOCK hit one\nMOCK hit two", "plain tool text"]
    assert E.tool_strings("Script failed\n" + json.dumps("x")) == []


# ---------------------------------------------------------------------------------------------- rules

FIRES = {
    "markets": ["Polymarket gives Abbott 80%.", "Hinojosa at 15% to win on the exchange.", "Contracts trade at 31¢."],
    "forecasts": ["Cook Political rates the race Lean Republican.", "The race is too close to call.",
                  "Abbott could lose in November.", "Polls point to a narrow lead.", "It was a dead heat."],
    "chances": ["Her chances improved.", "The odds shifted."],
    "expectations": ["Analysts expect a special session.", "A special session is unlikely.", "Experts believe it will pass."],
    "effects": ["A Hinojosa win would end the pause.", "If Hinojosa wins, the pause ends.", "Under a Hinojosa administration, rules change."],
    "tool_voice": ["The page does not answer your question.", "You asked for monthly values."],
}  # fmt: skip
STAYS = [
    "ERCOT paused approvals for large loads in June.",
    "The Comptroller estimated the exemption cost $3.2 billion.",
    "Texas will lose out on $3.2 billion in sales tax revenue.",
    "The poll surveyed 934 likely voters.",
    "NYT/Siena poll (https://www.reddit.com/r/fivethirtyeight/comments/abc/nyt_siena_tx_poll/)",
    "MOCK HOST: Governor, you mentioned the 20-year tax break.",
    "Hinojosa said she would end the tax break once she takes office.",
    "Hinojosa's plan would end the exemption.",
]


@pytest.mark.parametrize("rule, sentence", [(r, s) for r, ss in FIRES.items() for s in ss])
def test_each_rule_fires_on_its_kind(rule, sentence):
    assert E.screen_reason(sentence) == rule


@pytest.mark.parametrize("sentence", STAYS)
def test_facts_and_positions_stay(sentence):
    assert E.screen_reason(sentence) is None


def test_a_headline_inside_an_address_counts():
    assert E.screen_reason("- MOCK (https://news.example.com/abbott-could-lose-texas)") == "forecasts"
    assert E.screen_reason("https://example.com/poll-of-likely-voters") is None


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=120))
def test_screen_reason_is_a_rule_name_or_none(s):
    assert E.screen_reason(s) in (None, *E.SCREEN)


# --------------------------------------------------------------------------------- readers' corrections

DROPPED = "Analysts expect a special session."
KEPT = "ERCOT paused approvals for large loads in June."


def test_a_reader_removal_drops_a_sentence_no_rule_matches():
    r = Readers(removals=frozenset({E.sentence_key(KEPT)}))
    assert E.verdict(KEPT) is None and E.verdict(KEPT, r) == "reader"


def test_a_reader_keep_saves_a_sentence_a_rule_drops_and_removal_wins_over_keep():
    k = E.sentence_key(DROPPED)
    assert E.verdict(DROPPED, Readers(keeps=frozenset({k}))) is None
    assert E.verdict(DROPPED, Readers(removals=frozenset({k}), keeps=frozenset({k}))) == "reader"


def test_sentence_keys_ignore_white_space():
    assert E.sentence_key("A  b\tc ") == E.sentence_key("A b c")


def test_screen_line_counts_what_goes_and_what_readers_kept():
    counts, log = {}, []
    line = f"{KEPT} {DROPPED} Her chances improved."
    kept = E.screen_line(line, counts, log, Readers(keeps=frozenset({E.sentence_key(DROPPED)})))
    assert kept == f"{KEPT} {DROPPED}"
    assert counts["chances"] == 1 and counts["reader_kept"] == 1
    assert log == [("chances", "Her chances improved.")]


# --------------------------------------------------------------------------------- items and the file


def item(lines, label="Page", title="MOCK page (https://example.com)"):
    return Item(label, title, list(lines))


def test_market_pages_go_whole_and_failed_extracts_go_whole():
    market = item(["Kalshi has Abbott at 80.", "Polymarket agrees.", "ERCOT paused approvals."])
    failed = item(["The content provided does not include the requested information."], label="Extract")
    plain = item([KEPT])
    kept, counts = E.process([market, failed, plain])
    assert [it.lines for it in kept] == [[KEPT]]
    assert counts["market_items"] == 1 and counts["failed_extracts"] == 1 and counts["items_kept"] == 1


def test_duplicate_lines_go_and_titles_are_screened():
    a = item([KEPT, "Another fact."], title="Abbott could lose (https://example.com/a)")
    b = item([KEPT])
    kept, counts = E.process([a, b])
    assert kept[0].title == "" and counts["titles_screened"] == 1
    assert [it.lines for it in kept] == [[KEPT, "Another fact."]]
    assert counts["duplicate_lines"] == 1


lines_strategy = st.lists(
    st.lists(st.sampled_from([KEPT, DROPPED, "Her chances improved.", "Another fact.", "Polymarket agrees.",
                              "The pause began in June.", "L3: A numbered line."]), min_size=1, max_size=4).map(" ".join),
    min_size=1, max_size=6,
)  # fmt: skip


@settings(max_examples=200, deadline=None)
@given(st.lists(lines_strategy, min_size=1, max_size=5))
def test_trace_partitions_the_units_and_kept_text_holds_only_staying_units(items_lines):
    items = [item(ls, title="") for ls in items_lines]
    stay, go = E.trace(items)
    kept, _ = E.process(items)
    kept_units = [u for it in kept for ln in it.lines for u in E.units(ln)]
    assert set(kept_units) <= set(stay)
    assert all(E.verdict(u) is None for u in kept_units)
    assert all(reason in (*E.SCREEN, "market_item", "failed_extract") for reason, _ in go)


@settings(max_examples=100, deadline=None)
@given(st.lists(lines_strategy, min_size=1, max_size=5))
def test_the_evidence_file_is_deterministic_and_carries_its_hash(items_lines):
    items = [item(ls) for ls in items_lines]
    a, ca = E.compile_evidence(items)
    b, cb = E.compile_evidence(items)
    assert a == b and ca == cb
    assert a.startswith(E.HEADER)
    assert ca["chars"] == len(a)
    assert not re.search(r"\bchances\b|polymarket", a, re.I)


def test_no_step_shortens_an_item_line_it_keeps():
    long = "x" * 5000 + "."
    kept, _ = E.process([item([long])])
    assert kept[0].lines == [long]
