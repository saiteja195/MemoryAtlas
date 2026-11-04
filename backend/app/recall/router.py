"""Decides, by code, whether a question needs the extended investigator prompt.

Most questions use the original prompt unchanged, so their recorded replies (fixtures/llm_cache,
keyed by prompt and payload) still match. A question goes to the extended prompt only when it
needs something that prompt adds: a relative day or time of day, a summary of the day, the
person's to-dos, or a question about the memory itself.

Rules are case-insensitive regular expressions, checked in this fixed priority order; the first
route with a matching rule wins:

  1. memory   about the memory itself: the models, coverage, an explicit clock range, uncertainty
  2. todo     promises the person made and requests made of them
  3. time     a relative day or time of day ("today", "this morning", "tonight")
  4. summary  a summary or the shape of the day ("summarise", "what happened", "most time")

Memory and to-do come first because their questions often also hold a time word ("What did the
models read today?", "What did I say I would do today?") and they need their own tools. Time comes
before summary because a summary of "this morning" must first resolve the window.

A weekday name ("on Friday") is not a relative-time word here: it names a day the memory may not
hold, and the original prompt already handles it.
"""
import re

RULES: list[tuple[str, list[str]]] = [
    ("memory", [
        r"\bthe models?\b", r"\bmuse( spark| voice)?\b", r"\bmodel (calls?|usage)\b",
        r"\bcover(ed|age)\b", r"\bhow much of my (day|morning|afternoon|evening)\b",
        r"\b(between|from) \d{1,2}[:.]\d{2} (and|to|until) \d{1,2}[:.]\d{2}\b",
        r"\b(unsure|uncertain|not sure)\b", r"\bhow (confident|sure)\b",
    ]),
    ("todo", [
        r"\bi (said|say|told \w+|tell \w+) i('d| would| will)\b",
        r"\bdid i (promise|commit|agree)\b", r"\bi (promised|committed|agreed)\b",
        r"\b(promised?|committed) (anyone|anybody|someone|somebody)\b",
        r"\bask(ed)? me to\b", r"\bfollow(ed)?[ -]up\b", r"\bforg[eo]t to\b", r"\bto-?dos?\b",
    ]),
    ("time", [
        r"\b(today|tonight|yesterday)\b", r"\b(morning|afternoon|evening)\b",
    ]),
    ("summary", [
        r"\bsummar(y|ise|ize|ised|ized)\b", r"\bwhat happened\b", r"\bmost important\b",
        r"\bmost time\b", r"\b(highlights?|recap|overview)\b", r"\bmy day\b",
    ]),
]

_COMPILED = [(route, [re.compile(p, re.I) for p in patterns]) for route, patterns in RULES]


def needs_extended(question: str) -> str | None:
    """The route name ("memory", "todo", "time", "summary") or None for the original prompt."""
    for route, patterns in _COMPILED:
        if any(p.search(question) for p in patterns):
            return route
    return None
