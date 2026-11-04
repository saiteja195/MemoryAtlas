"""Recorded model replies (fixtures/llm_cache) are keyed by a hash of the request, so the existing
system prompts must stay byte-identical. A change here means re-recording the demo day."""
import hashlib

from app.compiler import extract
from app.recall import investigator


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_prompt_pins():
    assert digest(investigator.SYSTEM) == (
        "cc9690e4d8094e4a12dc2a29b9e409071331f1b1c1ebd3a7ecab252d7ef15fe9")
    assert digest(extract.SYSTEM) == (
        "89fc0286076c115ee4b9433c6978ad69d9407aba7d781dcc6df3134c4324b59f")
