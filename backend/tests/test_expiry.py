"""Consent expiry: a grant that lapses is forgotten exactly like one that is withdrawn."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import create_app
from app.config import Settings
from app.capture.models import RawCapture
from app.corrections import CorrectionError, correct_claim
from app.privacy import clock, probes
from app.privacy.consent import active_grant, create_grant
from app.privacy.filter import authorized_claim_ids, valid_source_ids

from .fakes import FakeLLM, claim
from .test_review_regressions import SECRET, World

T0 = clock.now()


def later(monkeypatch, hours):
    moment = T0 + timedelta(hours=hours)
    monkeypatch.setattr(clock, "now", lambda: moment)


def expiring_world(hours=2):
    """Me and Alex recorded a conversation; Alex's consent lasts `hours`. Me's does not expire."""
    w = World(rules=[("budget", [claim("Alex", "said", value="the budget is final", text="Alex said the budget is final")])])
    g_me = w.grant("me", "room")
    g_alex, token = create_grant(w.conn, SECRET, "alex", "room", expires_at=T0 + timedelta(hours=hours))
    w.tokens[g_alex] = token
    w.talk("room", "2026-10-29T12:00:00", ["me", "alex"], [("alex", "The budget is final"), ("me", "Understood")])
    w.note("room", "2026-10-29T12:30:00", "my own unrelated note")
    return w, g_me, g_alex


def test_before_expiry_nothing_changes(monkeypatch):
    w, g_me, g_alex = expiring_world()
    later(monkeypatch, 1)
    assert w.revoker.due() == [] and w.revoker.sweep(run_red_team=False) == []
    assert len(valid_source_ids(w.conn)) == 3


def test_an_expired_grant_is_refused_the_moment_it_lapses_even_before_any_purge(monkeypatch):
    """Defence in depth: nothing is readable once consent has lapsed, whether or not the sweep has run."""
    w, g_me, g_alex = expiring_world()
    later(monkeypatch, 3)
    assert w.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] > 0       # not purged yet
    assert valid_source_ids(w.conn) == {r[0] for r in w.conn.execute(
        "SELECT source_id FROM sources WHERE kind='user_confirmation'")}          # only Me's own note
    assert not any(c in authorized_claim_ids(w.conn) for c in
                   [r[0] for r in w.conn.execute("SELECT claim_id FROM claims WHERE predicate='said'")])


def test_sweeping_forgets_the_whole_recording_and_leaves_the_owners_own_note(monkeypatch):
    w, g_me, g_alex = expiring_world()
    later(monkeypatch, 3)
    (receipt,) = w.revoker.sweep(run_red_team=False)
    assert receipt["reason"] == "expired" and receipt["grant_id"] == g_alex
    assert receipt["removed"]["sources_blanked"] == 2                              # both lines, the owner's too
    assert w.conn.execute("SELECT COUNT(*) FROM claims WHERE predicate='said'").fetchone()[0] == 0
    assert w.conn.execute("SELECT COUNT(*) FROM sources WHERE status='active'").fetchone()[0] == 1
    row = w.conn.execute("SELECT revoked_at, ended_reason FROM consent_grants WHERE grant_id=?", (g_alex,)).fetchone()
    assert row["revoked_at"] and row["ended_reason"] == "expired"
    assert receipt["summary"]["probes_failed"] == 0 and receipt["summary"]["probes_passed"] == 6   # red team skipped here


def test_expiry_leaves_exactly_what_a_withdrawal_leaves(monkeypatch):
    a, _, ga = expiring_world()
    b, _, gb = expiring_world()
    a.revoker.revoke(ga, a.tokens[ga], run_red_team=False)
    later(monkeypatch, 3)
    b.revoker.sweep(run_red_team=False)

    def state(w):
        return ([tuple(r) for r in w.conn.execute("SELECT claim_id, text, status FROM claims ORDER BY claim_id")],
                [tuple(r) for r in w.conn.execute("SELECT source_id, status FROM sources ORDER BY source_id")],
                sorted(r[0] for r in w.conn.execute("SELECT entity_id FROM entities")))
    assert state(a) == state(b)


def test_sweeping_twice_changes_nothing_and_makes_one_receipt(monkeypatch):
    w, _, g_alex = expiring_world()
    later(monkeypatch, 3)
    first = w.revoker.sweep(run_red_team=False)
    assert len(first) == 1 and w.revoker.sweep(run_red_team=False) == []
    assert w.conn.execute("SELECT COUNT(*) FROM forgetting_receipts").fetchone()[0] == 1


def test_a_grant_with_no_expiry_never_lapses(monkeypatch):
    w, g_me, g_alex = expiring_world()
    later(monkeypatch, 24 * 365 * 5)
    assert g_me not in w.revoker.due() and g_alex in w.revoker.due()


def test_a_withdrawal_after_expiry_returns_the_same_receipt(monkeypatch):
    w, _, g_alex = expiring_world()
    later(monkeypatch, 3)
    (receipt,) = w.revoker.sweep(run_red_team=False)
    again = w.revoker.revoke(g_alex, w.tokens[g_alex], run_red_team=False)
    assert again["receipt_id"] == receipt["receipt_id"] and again["already_revoked"]


def test_new_captures_under_an_expired_grant_are_refused(monkeypatch):
    w, g_me, g_alex = expiring_world()
    later(monkeypatch, 3)
    assert active_grant(w.conn, "alex", "room") is None and active_grant(w.conn, "me", "room") == g_me
    res = w.talk("room", "2026-10-29T13:00:00", ["me", "alex"], [("alex", "Another thing"), ("me", "Ok")])
    assert all(r.ingest.status == "rejected" and r.ingest.reason == "no_consent" for r in res)


def test_an_owner_grant_that_lapsed_cannot_back_a_correction(monkeypatch):
    from app.corrections import _owner_session
    w = World()
    create_grant(w.conn, SECRET, "me", "s1", expires_at=T0 + timedelta(hours=1))
    assert _owner_session(w.conn, "me") == "s1"
    later(monkeypatch, 2)
    assert _owner_session(w.conn, "me") is None


def test_a_lapsed_grant_changes_the_answer_cache_key(monkeypatch):
    from app.recall.service import graph_version
    w, _, _ = expiring_world()
    before = graph_version(w.conn)
    later(monkeypatch, 3)
    assert graph_version(w.conn) != before             # a cached answer cannot outlive the consent


def test_a_grant_cannot_be_created_already_expired():
    w = World()
    with pytest.raises(ValueError):
        create_grant(w.conn, SECRET, "me", "s1", expires_at=T0 - timedelta(minutes=1))


def test_old_databases_gain_the_columns_and_keep_their_grants(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE consent_grants (grant_id TEXT PRIMARY KEY, grantor TEXT NOT NULL, scope TEXT NOT NULL,
          scope_ref TEXT NOT NULL, purposes TEXT NOT NULL, token_hash TEXT NOT NULL, granted_at TEXT NOT NULL, revoked_at TEXT);
        INSERT INTO consent_grants VALUES ('g1','me','capture_session','s','["personal_recall"]','h','t',NULL),
                                          ('g2','alex','capture_session','s','["personal_recall"]','h','t','t2');""")
    raw.commit()
    raw.close()
    conn = db.connect(path)
    rows = {r["grant_id"]: r for r in conn.execute("SELECT * FROM consent_grants")}
    assert rows["g1"]["expires_at"] is None and rows["g1"]["ended_reason"] is None
    assert rows["g2"]["ended_reason"] == "withdrawn"           # an earlier withdrawal is recorded as one


def test_the_graph_probe_passes_after_an_expiry(monkeypatch):
    w, _, g_alex = expiring_world()
    later(monkeypatch, 3)
    w.revoker.sweep(run_red_team=False)
    assert probes.graph_support(w.conn, []).status == "pass"


def test_a_receipt_is_written_even_if_verification_crashes_and_it_is_not_a_pass(monkeypatch):
    """The purge has committed by then. A check that could not run must show as a failure, never as a pass."""
    from app.privacy import revocation
    w, _, g_alex = expiring_world()
    later(monkeypatch, 3)

    def boom(*a, **k):
        raise RuntimeError("probe bug")
    monkeypatch.setattr(revocation, "run_probes", boom)
    (receipt,) = w.revoker.sweep(run_red_team=False)
    assert receipt["summary"]["all_passed"] is False and receipt["summary"]["probes_failed"] == 1
    assert w.conn.execute("SELECT COUNT(*) FROM forgetting_receipts").fetchone()[0] == 1
    assert w.conn.execute("SELECT COUNT(*) FROM claims WHERE predicate='said'").fetchone()[0] == 0


# -- the API ------------------------------------------------------------------------------------

def client_with(fake=None):
    return TestClient(create_app(Settings(auth=False, db_path=":memory:", llm_mode="replay"), fake or FakeLLM()))


def test_the_api_creates_an_expiring_grant_and_lists_it():
    c = client_with()
    r = c.post("/consent/grants", json={"grantor": "me", "session_id": "s9", "valid_for_hours": 2}).json()
    assert r["expires_at"]
    listed = {g["grant_id"]: g for g in c.get("/consent/grants").json()}
    assert listed[r["grant_id"]]["expires_at"] == r["expires_at"] and listed[r["grant_id"]]["ended_reason"] is None
    forever = c.post("/consent/grants", json={"grantor": "me", "session_id": "s10"}).json()
    assert forever["expires_at"] is None


@pytest.mark.parametrize("hours", [0, -1, 9000])
def test_the_api_rejects_a_nonsense_lifetime(hours):
    assert client_with().post("/consent/grants", json={"grantor": "me", "session_id": "s", "valid_for_hours": hours}).status_code == 422


def test_the_api_forgets_by_itself_once_a_grant_lapses(monkeypatch):
    fake = FakeLLM(rules=[("expiring note", [claim("Me", "said", value="remember this", text="Me said remember this")])])
    c = client_with(fake)
    gid = c.post("/consent/grants", json={"grantor": "me", "session_id": "s9", "valid_for_hours": 1}).json()["grant_id"]
    r = c.post("/capture/note", json={"session_id": "s9", "captured_at": "2026-10-29T10:00:00", "text": "an expiring note"})
    assert r.json()["results"][0]["status"] == "ingested"
    assert any(e["predicate"] == "said" for e in c.get("/graph").json()["edges"])
    later(monkeypatch, 2)
    edges = c.get("/graph").json()["edges"]                                  # the request itself triggers the purge
    assert not any(e["predicate"] == "said" for e in edges)
    grant = {g["grant_id"]: g for g in c.get("/consent/grants").json()}[gid]
    assert grant["ended_reason"] == "expired" and grant["receipt_id"]
    receipt = c.get(f"/receipts/{grant['receipt_id']}").json()
    assert receipt["reason"] == "expired"
    assert c.get("/health").status_code == 200


def test_the_expire_due_endpoint_is_idempotent(monkeypatch):
    c = client_with()
    c.post("/consent/grants", json={"grantor": "me", "session_id": "s9", "valid_for_hours": 1})
    later(monkeypatch, 2)
    first = c.post("/consent/expire-due").json()
    assert len(first["expired"]) in (0, 1)                                    # the request's own sweep may have run it
    assert c.post("/consent/expire-due").json() == {"expired": []}


def test_the_demo_can_let_alexs_consent_lapse_now():
    c = client_with()
    c.post("/demo/advance", params={"steps": 50})
    alex = next(g["grant_id"] for g in c.get("/consent/grants").json() if g["grantor"] == "alex")
    out = c.post(f"/demo/grants/{alex}/expire").json()
    assert len(out["expired"]) == 1
    texts = [e["text"] for e in c.get("/graph").json()["edges"]]
    assert not any("proposal" in t or "al pastor" in t for t in texts)
    assert any("met with" in t for t in texts)                                # the calendar still supports it
    assert c.post(f"/demo/grants/{alex}/expire").status_code == 404           # already ended
