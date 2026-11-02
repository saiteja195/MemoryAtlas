import hashlib

import numpy as np

DIM = 256


def embed(text: str) -> np.ndarray:
    """Local, deterministic feature-hashed character 3-grams. Meta's model list has no
    embedding model, and the corpus is small enough that this is adequate for retrieval."""
    vec = np.zeros(DIM, dtype=np.float32)
    t = f"  {text.lower()}  "
    for i in range(len(t) - 2):
        h = int.from_bytes(hashlib.blake2b(t[i:i + 3].encode(), digest_size=4).digest(), "big")
        vec[h % DIM] += 1.0 if (h >> 31) & 1 else -1.0
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))
