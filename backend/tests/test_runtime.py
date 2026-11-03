import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.profiles.runtime import Runtimes

from .fakes import FakeLLM


def settings(tmp_path, **kw):
    return Settings(db_path=str(tmp_path / "x.db"), llm_mode="live", cache_dir=str(tmp_path / "seed"), **kw)


def source_count(rt) -> int:
    return rt.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]


def test_runtimes_build_one_runtime_per_profile_and_cache_it(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    a = rts.get("aaaaaaaaaaaa", "A", False)
    assert rts.get("aaaaaaaaaaaa", "A", False) is a
    assert rts.get("bbbbbbbbbbbb", "B", False) is not a
    rts.close_all()


def test_runtime_files_live_under_the_profile_id_directory(tmp_path):
    root = tmp_path / "data"
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(root))
    rt = rts.get("aaaaaaaaaaaa", "A", False)
    assert rt.db_path == str(root / "profiles" / "aaaaaaaaaaaa" / "memoryatlas.db")
    assert rt.cache_dir == str(root / "profiles" / "aaaaaaaaaaaa" / "llmcache")
    assert os.path.exists(rt.db_path)
    rts.close_all()


def test_two_runtimes_have_separate_databases(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    a, b = rts.get("aaaaaaaaaaaa", "A", False), rts.get("bbbbbbbbbbbb", "B", False)
    a.conn.execute("INSERT INTO entities(entity_id, type, name) VALUES ('x','person','OnlyInA')")
    a.conn.commit()
    assert a.conn.execute("SELECT COUNT(*) FROM entities WHERE name='OnlyInA'").fetchone()[0] == 1
    assert b.conn.execute("SELECT COUNT(*) FROM entities WHERE name='OnlyInA'").fetchone()[0] == 0
    rts.close_all()


def test_evict_closes_the_connection(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    rt = rts.get("aaaaaaaaaaaa", "A", False)
    rts.evict("aaaaaaaaaaaa")
    with pytest.raises(sqlite3.ProgrammingError):
        rt.conn.execute("SELECT 1")
    assert rts.get("aaaaaaaaaaaa", "A", False) is not rt
    rts.close_all()


def test_runtime_without_seed_has_no_grants(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    rt = rts.get("aaaaaaaaaaaa", "A", False)
    assert rt.conn.execute("SELECT COUNT(*) FROM consent_grants").fetchone()[0] == 0
    seeded = rts.get("bbbbbbbbbbbb", "B", True)
    assert seeded.conn.execute("SELECT COUNT(*) FROM consent_grants").fetchone()[0] > 0
    rts.close_all()


def test_unseeded_runtime_still_has_an_owner_entity(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    rt = rts.get("aaaaaaaaaaaa", "A", False)
    assert rt.conn.execute("SELECT COUNT(*) FROM entities WHERE entity_id='me'").fetchone()[0] == 1
    rts.close_all()


def test_default_runtime_is_seeded_like_today(tmp_path):
    c = TestClient(create_app(settings(tmp_path, auth=False), FakeLLM()))
    assert c.get("/demo/status").status_code == 200           # no cookie needed
    assert c.get("/health").json()["auth"] is False
    assert c.app.state.conn.execute("SELECT COUNT(*) FROM consent_grants").fetchone()[0] > 0


def test_health_reports_auth_mode(tmp_path):
    c = TestClient(create_app(settings(tmp_path, auth=True), FakeLLM()))
    assert c.get("/health").json()["auth"] is True
