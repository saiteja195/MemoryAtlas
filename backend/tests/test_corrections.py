"""User corrections: a wrong fact becomes history, what rested only on it follows, nothing is deleted."""
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.corrections import CorrectionError, correct_claim
from app.privacy.filter import visible_claim_ids
from app.privacy.revocation import RevocationEngine

from .fakes import FakeLLM, claim


def one(conn, predicate):
    return conn.execute("SELECT * FROM claims WHERE predicate=? AND status='active'", (predicate,)).fetchone()


def status(conn, cid):
    return conn.execute("SELECT status, superseded_by FROM claims WHERE claim_id=?", (cid,)).fetchone()


def teach(fake, key, claims):
    fake.rules.append((key, claims))


def test_a_corrected_fact_becomes_history_and_the_replacement_takes_over(full_day, fake):
    teach(fake, "by Monday", [claim("Alex", "committed_to", value="send the proposal by Monday",
                                    text="Alex committed to send the proposal by Monday")])
    old = one(full_day.conn, "committed_to")
    out = correct_claim(full_day.engine, old["claim_id"], "Actually Alex will send the proposal by Monday")
    new = out["replacement"]
    assert status(full_day.conn, old["claim_id"])["status"] == "superseded"
    assert status(full_day.conn, old["claim_id"])["superseded_by"] == new
    row = full_day.conn.execute("SELECT status, evidence_type, text FROM claims WHERE claim_id=?", (new,)).fetchone()
    assert row["status"] == "active" and row["evidence_type"] == "user_confirmation" and "Monday" in row["text"]
    visible = visible_claim_ids(full_day.conn)
    assert new in visible and old["claim_id"] not in visible
    assert old["claim_id"] in visible_claim_ids(full_day.conn, include_history=True)     # kept as history


def test_what_was_derived_only_from_the_corrected_fact_is_set_aside_too(full_day, fake):
    said = one(full_day.conn, "said")
    assert one(full_day.conn, "recommended") is not None
    teach(fake, "Thai place", [claim("Alex", "said", value="try the Thai place", text="Alex said to try the Thai place")])
    out = correct_claim(full_day.engine, said["claim_id"], "No, Alex said to try the Thai place")
    assert one(full_day.conn, "recommended") is None
    assert out["also_superseded"]                                   # reported to the caller
    assert one(full_day.conn, "met_with") is not None                # still backed by the calendar


def test_only_claims_with_no_other_support_follow_the_corrected_one(conn):
    from app.corrections import dependents
    conn.execute("INSERT INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes, token_hash, granted_at)"
                 " VALUES ('g','me','capture_session','s','[\"personal_recall\"]','h','t')")
    conn.execute("INSERT INTO sources(source_id, kind, session_id, grant_id, captured_at, ingested_at, text, content_hash)"
                 " VALUES ('src','user_confirmation','s','g','2026-10-29T10:00:00','t','x','h')")
    conn.execute("INSERT INTO entities(entity_id, type, name) VALUES ('e','person','E')")
    for cid in "ABDEF":
        conn.execute("INSERT INTO claims(claim_id, subject_id, predicate, object_value, evidence_type, confidence, text,"
                     " created_at) VALUES (?,'e','p','v','inference',0.5,?, 't')", (cid, cid))
    jid = iter(range(100))

    def source(c):
        conn.execute("INSERT INTO justifications(justification_id, claim_id, kind, source_id) VALUES (?,?,'source','src')",
                     (f"j{next(jid)}", c))

    def derive(c, *premises):
        j = f"j{next(jid)}"
        conn.execute("INSERT INTO justifications(justification_id, claim_id, kind, rule) VALUES (?,?,'derivation','r')", (j, c))
        for p in premises:
            conn.execute("INSERT INTO justification_premises VALUES (?,?)", (j, p))

    source("A"); source("B")
    derive("D", "A"); derive("D", "B")        # D has two independent derivations: it survives losing A
    derive("E", "A")                           # E rests only on A
    derive("F", "E")                           # F rests only on E
    assert dependents(conn, {"A"}) == {"A", "E", "F"}


def test_a_retraction_sets_the_fact_aside_without_recording_anything(full_day):
    sources = full_day.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    old = one(full_day.conn, "committed_to")
    out = correct_claim(full_day.engine, old["claim_id"], retract=True)
    assert out["replacement"] is None and out["source_id"] is None
    assert status(full_day.conn, old["claim_id"])["status"] == "superseded"
    assert full_day.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == sources


def test_the_correction_rests_on_the_owners_own_consent_only(full_day, fake):
    teach(fake, "by Monday", [claim("Alex", "committed_to", value="send the proposal by Monday")])
    out = correct_claim(full_day.engine, one(full_day.conn, "committed_to")["claim_id"], "proposal by Monday")
    grants = [r[0] for r in full_day.conn.execute(
        "SELECT g.grantor FROM source_consents c JOIN consent_grants g USING(grant_id) WHERE c.source_id=?",
        (out["source_id"],))]
    assert grants == ["me"]


def test_a_correction_that_states_no_replacement_changes_nothing(full_day):
    old = one(full_day.conn, "committed_to")
    with pytest.raises(CorrectionError) as e:
        correct_claim(full_day.engine, old["claim_id"], "hmm, not sure about that")
    assert e.value.code == 422
    assert status(full_day.conn, old["claim_id"])["status"] == "active"


@pytest.mark.parametrize("kwargs", [{}, {"text": "x y z", "retract": True}])
def test_a_request_needs_exactly_one_of_text_or_retract(full_day, kwargs):
    with pytest.raises(CorrectionError) as e:
        correct_claim(full_day.engine, one(full_day.conn, "committed_to")["claim_id"], **kwargs)
    assert e.value.code == 422


def test_unknown_and_already_corrected_claims_are_refused(full_day):
    with pytest.raises(CorrectionError) as e:
        correct_claim(full_day.engine, "clm-doesnotexist", retract=True)
    assert e.value.code == 404
    old = one(full_day.conn, "committed_to")["claim_id"]
    correct_claim(full_day.engine, old, retract=True)
    with pytest.raises(CorrectionError) as e:
        correct_claim(full_day.engine, old, retract=True)
    assert e.value.code == 409


def test_a_forgotten_fact_cannot_be_corrected_and_is_not_confirmed_to_exist(full_day):
    old = one(full_day.conn, "committed_to")["claim_id"]
    alex = full_day.conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'").fetchone()[0]
    RevocationEngine(full_day.conn, "test-secret", FakeLLM(), "me").revoke(
        alex, full_day.tokens["alex:sync-alex"], run_red_team=False)
    with pytest.raises(CorrectionError) as e:
        correct_claim(full_day.engine, old, retract=True)
    assert e.value.code == 404 and e.value.message == "unknown claim"


def test_a_wrong_sighting_that_was_disputed_stops_being_disputed_once_set_aside(full_day):
    conn = full_day.conn
    wallet = conn.execute("SELECT subject_id FROM claims WHERE predicate='located_at' LIMIT 1").fetchone()[0]
    a, b = [r[0] for r in conn.execute(
        "SELECT claim_id FROM claims WHERE predicate='located_at' AND subject_id=? ORDER BY event_time", (wallet,))][:2]
    conn.execute("UPDATE claims SET status='disputed' WHERE claim_id IN (?,?)", (a, b))
    conn.commit()
    correct_claim(full_day.engine, a, retract=True)
    assert status(conn, a)["status"] == "superseded"
    assert status(conn, b)["status"] == "active"                    # nothing left to contradict


def test_the_api_corrects_a_claim_and_reports_errors():
    s = Settings(auth=False, db_path=":memory:", llm_mode="replay")
    fake = FakeLLM()
    client = TestClient(create_app(s, fake))
    client.post("/demo/advance", params={"steps": 50})
    teach(fake, "by Monday", [claim("Alex", "committed_to", value="send the proposal by Monday")])
    old = client.app.state.conn.execute("SELECT claim_id FROM claims WHERE predicate='committed_to'").fetchone()[0]
    r = client.post(f"/claims/{old}/correct", json={"text": "Actually the proposal comes by Monday"})
    assert r.status_code == 200
    new = r.json()["replacement"]
    assert new and new != old
    assert client.post("/claims/clm-nope/correct", json={"retract": True}).status_code == 404
    assert client.post(f"/claims/{old}/correct", json={"retract": True}).status_code == 409   # already history
    assert client.post(f"/claims/{new}/correct", json={}).status_code == 422
    now = {e["id"]: e for e in client.get("/graph").json()["edges"]}
    assert old not in now and now[new]["status"] == "active" and now[new]["evidence_type"] == "user_confirmation"
    hist = {e["id"]: e for e in client.get("/graph", params={"include": "history"}).json()["edges"]}
    assert hist[old]["status"] == "superseded" and hist[old]["superseded_by"] == new


def test_a_claim_whose_consent_is_gone_cannot_be_corrected_even_before_the_purge_runs(full_day):
    """Defence in depth: the row still exists, but nothing authorises it, so it is unknown to the caller."""
    old = one(full_day.conn, "committed_to")["claim_id"]
    full_day.conn.execute("UPDATE consent_grants SET revoked_at='t' WHERE grantor='alex'")
    full_day.conn.commit()
    assert full_day.conn.execute("SELECT 1 FROM claims WHERE claim_id=?", (old,)).fetchone()
    with pytest.raises(CorrectionError) as e:
        correct_claim(full_day.engine, old, retract=True)
    assert e.value.code == 404
