from pathlib import Path

import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.config import ROOT
from app.demo import DemoRunner
from app.engine import MemoryEngine

from .fakes import FakeLLM

SCRIPT = ROOT / "fixtures" / "demo_day" / "script.yaml"


@pytest.fixture
def conn():
    return db.connect()


@pytest.fixture
def adapter():
    return MockDayAdapter(SCRIPT)


@pytest.fixture
def fake():
    return FakeLLM()


@pytest.fixture
def demo(conn, fake, adapter):
    engine = MemoryEngine(conn, fake, adapter.owner, adapter.names)
    return DemoRunner(engine, adapter, "test-secret")


@pytest.fixture
def played(demo):
    """The whole scheduled demo day, played with the fake model."""
    results = demo.advance(50)
    assert not any(r["rejected"] for r in results), results
    return demo


@pytest.fixture
def full_day(played):
    """Scheduled day plus the live-uploaded frame F4 (wallet in the car)."""
    played.play("F4")
    return played
