"""Local text embeddings (Meta's model list has no embedding model).

Feature-hashed character 3-grams, kept as small INTEGER counts. Ranking uses exact integer
arithmetic on those counts, never floating point, because what the model is shown depends on the
ranking and recorded responses are keyed by what it was shown: float summation order differs
between BLAS libraries and CPUs, and near-ties then rank differently on another machine.
"""
import hashlib
import math
from fractions import Fraction
from typing import Iterable

import numpy as np

DIM = 256


def counts(text: str) -> np.ndarray:
    """Signed 3-gram bucket counts (exact integers)."""
    vec = np.zeros(DIM, dtype=np.int16)
    t = f"  {text.lower()}  "
    for i in range(len(t) - 2):
        h = int.from_bytes(hashlib.blake2b(t[i:i + 3].encode(), digest_size=4).digest(), "big")
        vec[h % DIM] += 1 if (h >> 31) & 1 else -1
    return vec


def to_blob(c: np.ndarray) -> bytes:
    return np.asarray(c, dtype="<i2").tobytes()


def from_blob(blob: bytes, text: str) -> np.ndarray:
    """Stored counts. Rows written by an earlier version held float32 vectors; those are rebuilt
    from the claim's own text."""
    if len(blob) == DIM * 2:
        return np.frombuffer(blob, dtype="<i2").astype(np.int64)
    return counts(text).astype(np.int64)


def _dot(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.dot(np.asarray(a, dtype=np.int64), np.asarray(b, dtype=np.int64)))


def similarity(q: np.ndarray, c: np.ndarray) -> Fraction:
    """A value that orders exactly like cosine similarity: sign(dot) * dot^2 / (|q|^2 |c|^2),
    computed with integers and exact fractions."""
    dot = _dot(q, c)
    norms = _dot(q, q) * _dot(c, c)
    if dot == 0 or norms == 0:
        return Fraction(0)
    return Fraction(dot * abs(dot), norms)


def rank(q: np.ndarray, items: Iterable[tuple[str, np.ndarray]]) -> list[str]:
    """Ids, most similar first. Exact ties go to the larger id, the same on every machine."""
    scored = sorted(((similarity(q, c), i) for i, c in items), reverse=True)
    return [i for _, i in scored]


# Normalised float vectors, for callers that want a plain cosine (not used for ranking).
def embed(text: str) -> np.ndarray:
    c = counts(text).astype(np.int64)
    n = math.sqrt(_dot(c, c))
    return (c / n).astype(np.float32) if n else np.zeros(DIM, dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))
