"""Recorded model responses are keyed by what the model was shown, and what it is shown depends on
search rankings. Rankings therefore must not depend on the platform: BLAS libraries and CPUs add
floating point numbers in different orders, which flips near-ties and makes a recording fail to
replay on another machine (the independent review saw exactly that on macOS arm64).
"""
import numpy as np
import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.config import ROOT, Settings
from app.demo import DemoRunner
from app.engine import MemoryEngine
from app.llm.replay import RecordReplayClient
from app.recall.tools import RecallTools

QUESTIONS = [
    "Which restaurant did Alex recommend when we met near the office?", "Where is my wallet?",
    "Did I leave my wallet at the café?", "What is Alex's phone number?", "Which gym did I go to?",
    "Who did I have lunch with on Friday?", "What did Alex promise me?", "Alex", "restaurant", "wallet photo",
    "awning colour", "Tell me everything from my meeting with Alex.", "Summarize my afternoon.",
    "what happened in the morning", "unrelated nonsense words here",
]


@pytest.fixture(scope="module")
def day():
    s = Settings()
    adapter = MockDayAdapter(s.demo_script)
    llm = RecordReplayClient(str(ROOT / "fixtures" / "llm_cache"), "replay")
    conn = db.connect()
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, "s")
    demo.advance(50)
    demo.play("F4")
    return conn


def rankings(conn):
    out = {}
    for q in QUESTIONS:
        t = RecallTools(conn)
        out[q] = [(h["claim_id"], h["status"]) for h in t.run("search_claims", {"query": q, "k": 12})]
    return out


def other_platform(monkeypatch, how):
    """Make numpy's float summation behave like another BLAS would."""
    real_dot, real_norm = np.dot, np.linalg.norm

    def one_d(a, b):
        return getattr(a, "ndim", 0) == 1 and getattr(b, "ndim", 0) == 1

    if how == "double":
        monkeypatch.setattr(np, "dot", lambda a, b: real_dot(np.asarray(a, np.float64), np.asarray(b, np.float64)) if one_d(a, b) else real_dot(a, b))
        monkeypatch.setattr(np.linalg, "norm", lambda a, *x, **k: real_norm(np.asarray(a, np.float64), *x, **k))
    else:   # a different summation order
        monkeypatch.setattr(np, "dot", lambda a, b: np.float32(np.sum((np.asarray(a) * np.asarray(b))[::-1], dtype=np.float32)) if one_d(a, b) else real_dot(a, b))


@pytest.mark.parametrize("how", ["double", "reversed"])
def test_search_rankings_do_not_depend_on_the_platforms_float_arithmetic(day, monkeypatch, how):
    here = rankings(day)
    other_platform(monkeypatch, how)
    assert rankings(day) == here


def test_ranking_uses_exact_integer_similarity_so_ties_are_decided_by_rule_not_by_noise():
    from app.embed import counts, rank
    q = counts("alex wallet")
    items = [(c, counts(t)) for c, t in [("a", "alex wallet"), ("b", "alex wallet"), ("c", "billboard"), ("d", "wallet")]]
    ordered = rank(q, items)
    assert ordered[:2] == ["b", "a"]                       # identical texts tie exactly; larger id first
    assert ordered.index("d") < ordered.index("c")
