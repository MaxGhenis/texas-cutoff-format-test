"""Read a context's answer: the JSON object its final message carries, checked against the template
its brief gave it.

A grid context answers every question at the six cells; an isolated context answers at its one cell
and restates its scenario. `parse` checks a filled template and raises `ResponseError` with every
problem it finds. `read_answer` reads an answer as written first; only an answer that fails gets the
registered repairs, the same in every arm, before `parse` checks it again.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field

from .jump import BINARY, CELLS, KEYS, QUANTILES, QUANTITY, QUESTIONS, SENATE_BOUNDS

QUANTILE_KEYS = tuple(f"p{round(q * 100):02d}" for q in QUANTILES)
SHARE_TOLERANCE = 0.05  # a restated share within this of the assigned one counts as the same scenario


class ResponseError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s):\n" + "\n".join(f"- {p}" for p in problems))
        self.problems = problems


@dataclass
class Answer:
    """A checked answer. `values[question][key]` is a probability (yes/no questions) or the five
    quantiles in order (Talarico's share)."""

    values: dict[str, dict[str, object]]
    forecaster: dict = field(default_factory=dict)
    scenario: dict | None = None
    reasoning: dict[str, str] = field(default_factory=dict)


_PLAIN = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _number(x) -> float | None:
    """A JSON number, or a string that holds one plain decimal number and nothing else. A string with a
    percent sign or a thousands or decimal comma does not count: "1%" is not 0.01 or 1."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, str):
        x = x.strip()
        if not _PLAIN.fullmatch(x):
            return None
    elif not isinstance(x, (int, float)):
        return None
    try:
        v = float(x)
    except (OverflowError, ValueError):
        return None
    return v if math.isfinite(v) else None


def expected_winner(cell: float) -> str:
    return "hinojosa" if cell > 50.0 else "abbott"


def parse(obj, keys: tuple[str, ...], cell: float | None = None) -> Answer:
    """Check a parsed answer. `keys` are the forecast keys its template had (the six cells, or one);
    `cell` is the assigned share of an isolated context, whose answer must restate its scenario."""
    if not isinstance(obj, dict) or not isinstance(obj.get("nodes"), dict):
        raise ResponseError(["the answer must be an object with a 'nodes' object"])
    problems: list[str] = []
    out = Answer(values={})
    out.forecaster = obj.get("forecaster") if isinstance(obj.get("forecaster"), dict) else {}
    prior = out.forecaster.get("prior_context")
    if not isinstance(prior, str) or not prior.strip():
        problems.append("forecaster.prior_context: required; describe anything beyond the brief, or write 'none'")
    nodes = obj["nodes"]
    for q in QUESTIONS:
        item = nodes.get(q)
        forecasts = item.get("forecasts") if isinstance(item, dict) else None
        if not isinstance(forecasts, dict):
            problems.append(f"{q}: missing, or 'forecasts' missing")
            continue
        vals: dict[str, object] = {}
        for key in keys:
            v = forecasts.get(key)
            if not isinstance(v, dict):
                problems.append(f"{q}[{key}]: missing")
                continue
            checked = _check_value(q, v, f"{q}[{key}]", problems)
            if checked is not None:
                vals[key] = checked
        extra = set(forecasts) - set(keys)
        if extra:
            problems.append(f"{q}: {len(extra)} unexpected forecast key(s)")
        out.values[q] = vals
        out.reasoning[q] = item.get("reasoning") if isinstance(item.get("reasoning"), str) else ""
    unknown = set(nodes) - set(QUESTIONS)
    if unknown:
        problems.append(f"{len(unknown)} unexpected question(s)")
    if cell is not None:
        out.scenario = obj.get("scenario") if isinstance(obj.get("scenario"), dict) else None
        problems += _scenario_problems(out.scenario, cell)
    if problems:
        raise ResponseError(problems)
    return out


def _shown(value) -> str:
    """How a problem shows a value the model wrote: a number as written, anything else by its kind and
    size. Problems go to the public tables, and a model's text can quote its evidence file."""
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        return f"a string of {len(value)} characters"
    if isinstance(value, (list, dict)):
        return f"a {type(value).__name__} of {len(value)} items"
    return type(value).__name__


def _check_value(question: str, v: dict, where: str, problems: list[str]):
    if question in BINARY:
        p = _number(v.get("p"))
        if p is None or not 0.0 <= p <= 1.0:
            problems.append(f"{where}: p must be a probability from 0 to 1, got {_shown(v.get('p'))}")
            return None
        return p
    if question in QUANTITY:
        xs = [_number(v.get(k)) for k in QUANTILE_KEYS]
        if any(x is None for x in xs):
            missing = [k for k, x in zip(QUANTILE_KEYS, xs) if x is None]
            problems.append(f"{where}: quantiles {list(QUANTILE_KEYS)} must all be numbers; {missing} are not")
            return None
        lo, hi = SENATE_BOUNDS
        if any(b < a for a, b in zip(xs, xs[1:])):
            problems.append(f"{where}: quantiles must not decrease, got {xs}")
            return None
        if xs[0] < lo or xs[-1] > hi:
            problems.append(f"{where}: quantiles must lie in [{lo}, {hi}], got {xs}")
            return None
        return xs
    raise KeyError(question)


def _scenario_problems(scenario: dict | None, cell: float) -> list[str]:
    """An isolated context restates its scenario after its forecasts. A missing or different scenario
    fails the answer: the context may have forecast under another one."""
    if scenario is None:
        return ["scenario: missing; restate Hinojosa's share and the winner"]
    problems = []
    share = _number(scenario.get("hinojosa_share"))
    if share is not None and 0.0 < share < 1.0:
        share *= 100.0  # a share written as a fraction
    if share is None or abs(share - cell) > SHARE_TOLERANCE:
        problems.append(f"scenario.hinojosa_share: {_shown(scenario.get('hinojosa_share'))} is not the assigned {cell:g}")
    winner = scenario.get("winner")
    text = winner.lower() if isinstance(winner, str) else ""
    right, wrong = expected_winner(cell), expected_winner(100.0 - cell)
    if right not in text or wrong in text:
        problems.append(f"scenario.winner: {_shown(winner)} does not name {right.title()} alone")
    return problems


# ----------------------------------------------------------------------------------------- extraction

_FENCE = re.compile(r"^[ \t]*```[^\n`]*\n(.*?)\n[ \t]*```", re.S | re.M)

# The registered repairs, the two that github.com/MaxGhenis/alaska-senate-brief-experiment registered
# (its src/i86/response.py). `read_answer`
# reads an answer as written first and returns it unrepaired when `parse` accepts it. Only an answer
# that fails gets the repairs, the same in every arm, before `parse` checks it again. Each mends a slip
# that carries no forecast, and nothing else:
# - a comma that follows an element and has only white space between it and a closing brace or bracket,
#   outside strings, goes, when the JSON parses only without it;
# - a key that the template lacks, inside a question's `forecasts` or among `nodes`, goes when its value
#   holds no object (null, text, a number, true or false, or a list with no object in it at any depth):
#   only an object can hold a forecast.
# An answer that needs any other change fails. `cutoff analyze` reports the results without the repaired
# answers beside the main ones.


def _strip_trailing_commas(text: str) -> tuple[str, list[str]]:
    """`text` without each comma that, outside strings, follows an element and has only white space
    between it and a closing brace or bracket; and the text just before each comma removed. A comma
    after `{`, `[`, `:` or another comma stays: it follows no element."""
    out: list[str] = []
    removed: list[str] = []
    in_string = escaped = False
    comma: tuple[int, int] | None = None
    prev = ""
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string, prev = False, '"'
        elif ch == '"':
            in_string, comma = True, None
        elif ch in "}]" and comma is not None:
            out[comma[0]] = ""
            removed.append(text[max(0, comma[1] - 40) : comma[1] + 1])
            comma, prev = None, ch
        elif ch == ",":
            comma = (len(out), i) if prev == '"' or prev in ("}", "]") or prev.isalnum() else None
            prev = ch
        elif not ch.isspace():
            comma, prev = None, ch
        out.append(ch)
    return "".join(out), removed


def _loads(text: str) -> tuple[object, list[dict]]:
    try:
        return json.loads(text), []
    except json.JSONDecodeError as exc:
        fixed, removed = _strip_trailing_commas(text)
        if not removed:
            raise
        try:
            obj = json.loads(fixed)
        except json.JSONDecodeError:
            raise exc from None
        return obj, [{"repair": "trailing_comma", "count": len(removed), "before": removed}]


def extract_json(text: str, repairs: list | None = None, repair: bool = True) -> dict:
    """The answer in a final message: its last fenced block that names a "nodes" key, whatever the
    block's tag; with no such block, the outermost object. Only that one block counts: when it does
    not parse, the answer fails, and no earlier block stands in for it. With `repair`, a block that
    parses only without its trailing commas is read without them."""

    def load(t: str) -> tuple[object, list[dict]]:
        try:
            return _loads(t) if repair else (json.loads(t), [])
        except ValueError as exc:  # JSONDecodeError, and the integer-length limit json.loads enforces
            raise ResponseError([f"the answer's JSON does not parse: {exc}"]) from exc

    blocks = [b for b in _FENCE.findall(text) if '"nodes"' in b]
    if blocks:
        candidate = blocks[-1]
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ResponseError(["no JSON object found in the answer"])
        candidate = text[start : end + 1]
    obj, fixes = load(candidate)
    if repairs is not None:
        repairs.extend(fixes)
    return obj


def _holds_object(value) -> bool:
    if isinstance(value, dict):
        return True
    return isinstance(value, list) and any(_holds_object(v) for v in value)


def drop_strays(obj, keys: tuple[str, ...]) -> list[dict]:
    """Drop from a parsed answer, in place, each key the template lacks whose value holds no object,
    among `nodes` or inside a question's `forecasts`; return a record of each."""
    fixes: list[dict] = []
    if not isinstance(obj, dict) or not isinstance(obj.get("nodes"), dict):
        return fixes
    nodes = obj["nodes"]
    for key in list(nodes):
        if key not in QUESTIONS and not _holds_object(nodes[key]):
            fixes.append({"repair": "dropped_key", "where": "nodes", "key": key, "value": nodes.pop(key)})
    for q in QUESTIONS:
        item = nodes.get(q)
        forecasts = item.get("forecasts") if isinstance(item, dict) else None
        if not isinstance(forecasts, dict):
            continue
        for key in list(forecasts):
            if key not in keys and not _holds_object(forecasts[key]):
                fixes.append({"repair": "dropped_key", "where": f"{q}.forecasts", "key": key, "value": forecasts.pop(key)})
    return fixes


def read_answer(text: str, keys: tuple[str, ...], cell: float | None = None) -> tuple[Answer, list[dict]]:
    """A final message's checked answer and a record of each repair made (none when the answer passes
    as written). Raises `ResponseError` when the answer fails even after the registered repairs."""
    repairs: list[dict] = []
    obj = extract_json(text, repairs)
    if not repairs:  # it parses as written: check it as written first
        try:
            return parse(copy.deepcopy(obj), keys, cell), []
        except ResponseError:
            pass
    repairs += drop_strays(obj, keys)
    return parse(obj, keys, cell), repairs


def keys_for(arm: str, cell_key: str) -> tuple[tuple[str, ...], float | None]:
    """The forecast keys and assigned cell of a context, from its arm and its row's `cell`."""
    if arm == "grid":
        return KEYS, None
    return (cell_key,), CELLS[KEYS.index(cell_key)]
