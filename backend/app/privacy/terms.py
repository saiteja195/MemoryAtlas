"""Finding the words that identify what was forgotten.

A probe term is a short phrase that appeared in the removed material and appears nowhere in
what remains, so finding it again anywhere is proof of a leak, never a false alarm.
"""
import hashlib
import re

_STOP = {"about", "there", "their", "which", "would", "could", "should", "these", "those",
         "where", "while", "after", "before", "being", "other", "again", "think", "right",
         "the", "and", "for", "with", "from", "that", "this", "have", "has", "had", "will",
         "your", "you", "are", "was", "were", "been", "its", "they", "them", "then", "than",
         "not", "but", "can", "did", "does", "into", "over", "under", "near", "across", "just",
         "also", "very", "some", "any", "all", "out", "off", "our", "his", "her", "she", "him"}
_TOKEN = re.compile(r"[\w']+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [t.strip("'") for t in _TOKEN.findall(text.lower()) if t.strip("'")]


def _grams(text: str, n: int) -> set[str]:
    toks = tokens(text)
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def distinctive_terms(removed: list[str], remaining: list[str], cap: int = 60) -> list[str]:
    """Phrases (1 to 3 words) found in `removed` text and in none of the `remaining` text.
    Shortest first (most sensitive); single words only when they are at least 5 letters and not filler."""
    kept: dict[int, set[str]] = {n: set().union(*[_grams(t, n) for t in remaining] or [set()])
                                 for n in (1, 2, 3)}
    out: list[str] = []
    for n in (1, 2, 3):
        found: set[str] = set()
        for t in removed:
            for g in _grams(t, n):
                if g in kept[n] or g in found:
                    continue
                if n == 1 and (len(g) < 5 or g in _STOP or g.isdigit()):
                    continue
                # A phrase needs at least two content words; otherwise it is mostly glue
                # ("across the", "the office") and would flag ordinary paraphrase.
                if n > 1 and sum(len(w) >= 4 and w not in _STOP for w in g.split()) < 2:
                    continue
                # A shorter distinctive term already catches every occurrence of this phrase.
                if any(f" {o} " in f" {g} " for o in out):
                    continue
                found.add(g)
        out += sorted(found)
    return out[:cap]


def rare_terms(terms: list[str], known: list[str]) -> list[str]:
    """Terms with at least one word that appears nowhere in `known` (what remains plus the app's
    own vocabulary). For judging free-form model text: a phrase built only from everyday words
    ("alex said") matches paraphrases of the question, which is not a leak."""
    words = {w for t in known for w in tokens(t)}
    return [t for t in terms if any(w not in words for w in t.split())]


def term_digest(term: str) -> str:
    return hashlib.sha256(term.encode()).hexdigest()[:16]
