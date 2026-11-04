"""Slow and retried model calls leave a trace in the server log, so a long save can be explained."""
import logging

import httpx

from app import db
from app.llm import metered
from app.llm.meta import MetaClient
from app.llm.metered import MeteredLLM, usage_purpose

from .test_meta_client import responses_body

MODELS = {"text": "m", "asr": "a"}


class Quiet:
    """A model that answers {} at once."""
    mode = "live"

    def complete_json(self, system, user, schema):
        return {}


def test_every_model_call_is_logged_with_its_kind_purpose_and_time(caplog):
    llm = MeteredLLM(Quiet(), db.connect(), MODELS)
    with caplog.at_level(logging.INFO, logger="memoryatlas.llm"), usage_purpose("read_memory"):
        llm.complete_json("sys", "user", {})
    line = next(r.getMessage() for r in caplog.records if r.name == "memoryatlas.llm")
    assert "text" in line and "read_memory" in line and "live" in line and "s" in line


def test_a_slow_call_is_a_warning(caplog, monkeypatch):
    monkeypatch.setattr(metered, "SLOW_CALL_S", 0.0)
    llm = MeteredLLM(Quiet(), db.connect(), MODELS)
    with caplog.at_level(logging.INFO, logger="memoryatlas.llm"):
        llm.complete_json("sys", "user", {})
    assert any(r.levelno == logging.WARNING and "slow model call" in r.getMessage() for r in caplog.records)


def test_a_fast_call_is_not_a_warning(caplog):
    llm = MeteredLLM(Quiet(), db.connect(), MODELS)
    with caplog.at_level(logging.INFO, logger="memoryatlas.llm"):
        llm.complete_json("sys", "user", {})
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_a_retry_is_logged_with_why_and_how_long_it_waits(caplog):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503, text="busy") if len(calls) < 3 else httpx.Response(200, json=responses_body("{}"))

    c = MetaClient("https://api.meta.ai", "sk-secret", "muse-spark-1.3",
                   http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with caplog.at_level(logging.INFO, logger="memoryatlas.llm"):
        c.complete_json("sys", "user", {})
    retries = [r.getMessage() for r in caplog.records if "retry" in r.getMessage().lower()]
    assert len(retries) == 2 and "503" in retries[0] and "attempt 1" in retries[0]
    assert all("sk-secret" not in r.getMessage() for r in caplog.records)      # the key is never logged
