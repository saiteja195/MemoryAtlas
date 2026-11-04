import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import create_app
from app.capture.models import RawCapture
from app.config import Settings
from app.demo import DemoRunner
from app.engine import MemoryEngine
from app.llm.base import LLMUnavailable
from app.privacy import probes
from app.privacy.consent import create_grant
from app.privacy.export import export_memories
from app.privacy.filter import authorized_claim_ids
from app.privacy.revocation import BadToken, RevocationEngine, UnknownGrant, digest
from app.privacy.terms import distinctive_terms
from app.recall.service import RecallService

from .fakes import FakeLLM, claim

SECRET = "test-secret"


def alex(demo):
    gid = demo.conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'"
                            ).fetchone()[0]
    return gid, demo.tokens["alex:sync-alex"]


def engine(demo, **kw):
    return RevocationEngine(demo.conn, SECRET, demo.engine.llm, **kw)


def texts(conn):
    return [r[0] for r in conn.execute("SELECT text FROM claims")]


def snapshot(conn):
    """Everything that revocation could change, as comparable data."""
    out = {}
    for t in ("claims", "sources", "entities", "justifications", "justification_premises",
              "claim_index", "claim_vectors", "answer_cache", "chat_messages", "blocked_hashes"):
        out[t] = sorted(map(tuple, conn.execute(f"SELECT * FROM {t}").fetchall()))
    return out


# -- the Act 4 outcome ------------------------------------------------------------------------

def test_what_only_the_conversation_supported_is_gone(full_day):
    conn = full_day.conn
    gid, token = alex(full_day)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    left = " | ".join(texts(conn)).lower()
    for gone in ("promise", "proposal", "recommended luna", "taco place", "al pastor"):
        assert gone not in left
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE predicate IN ('said','committed_to',"
                        "'recommended','same_as','across_from')").fetchone()[0] == 0
    assert receipt["removed"]["claims_deleted"] >= 6
    assert receipt["removed"]["claims_deleted_by_kind"]["recommended"] == 1


def test_what_other_sources_support_survives(full_day):
    conn = full_day.conn
    gid, token = alex(full_day)
    engine(full_day).revoke(gid, token, run_red_team=False)
    left = " | ".join(texts(conn))
    assert "Me met with Alex" in left                     # the calendar still supports it
    assert "Luna Taqueria has a green awning" in left    # the sign still supports it
    assert "Orbit Fitness" in left and "The wallet was in the car" in left   # untouched
    ids = {r[0] for r in conn.execute("SELECT claim_id FROM claims")}
    assert ids <= authorized_claim_ids(conn)


def test_receipt_explains_why_survivors_survived(full_day):
    gid, token = alex(full_day)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    met = next(r for r in receipt["retained"] if r["text"] == "Me met with Alex")
    assert any(s.startswith("transcript_segment") for s in met["lost_support"])
    assert any(s.startswith("calendar_event") for s in met["still_supported_by"])
    k = receipt["kept"]
    assert k["claims_surviving"] == k["claims_that_lost_a_source_but_survive"] + k["claims_unaffected"]


def test_receipt_holds_counts_and_digests_not_the_forgotten_text(full_day):
    conn = full_day.conn
    gid, token = alex(full_day)
    dead = {r[0] for r in conn.execute("SELECT claim_id FROM claims WHERE predicate IN ("
                                       "'said','committed_to','recommended')")}
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    blob = json.dumps(receipt).lower()
    for gone in ("pastor", "proposal", "friday", "awning is", "promise"):
        assert gone not in blob
    assert not any(c in blob for c in dead)
    assert receipt["digests"]["removed_claim_ids_sha256"] and receipt["digests"]["probe_terms"]
    stored = json.loads(conn.execute("SELECT report_json FROM forgetting_receipts").fetchone()[0])
    assert stored["receipt_id"] == receipt["receipt_id"]


def test_sources_are_blanked_and_their_content_is_blocked(full_day):
    conn = full_day.conn
    gid, token = alex(full_day)
    hashes = [r[0] for r in conn.execute("SELECT content_hash FROM sources WHERE grant_id=?",
                                         (gid,))]
    assert hashes
    engine(full_day).revoke(gid, token, run_red_team=False)
    rows = conn.execute("SELECT * FROM sources WHERE grant_id=?", (gid,)).fetchall()
    assert rows and all(r["status"] == "revoked" and r["text"] is None and r["lat"] is None
                        and r["session_id"] is None for r in rows)
    blocked = {r[0] for r in conn.execute("SELECT content_hash FROM blocked_hashes")}
    assert set(hashes) <= blocked
    others = conn.execute("SELECT COUNT(*) FROM sources WHERE grant_id != ? AND text IS NOT NULL",
                          (gid,)).fetchone()[0]
    assert others >= 5                                    # other people's sources are untouched


def test_replaying_the_day_cannot_bring_it_back(full_day):
    gid, token = alex(full_day)
    engine(full_day).revoke(gid, token, run_red_team=False)
    before = snapshot(full_day.conn)
    out = full_day.play("A1")
    assert {r.ingest.reason for r in out} == {"no_consent"}
    # even under a brand-new grant the identical words are refused by hash
    create_grant(full_day.conn, SECRET, "alex", "sync-alex")
    again = full_day.play("A1")
    assert {r.ingest.reason for r in again} <= {"blocked", "duplicate"}
    assert snapshot(full_day.conn)["claims"] == before["claims"]


def test_entities_only_the_conversation_knew_are_deleted(full_day):
    conn = full_day.conn
    assert conn.execute("SELECT 1 FROM entities WHERE entity_id='place:taco-place'").fetchone()
    gid, token = alex(full_day)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    names = {r[0] for r in conn.execute("SELECT name FROM entities")}
    assert "taco place" not in names and {"Alex", "Luna Taqueria", "Me"} <= names
    assert receipt["removed"]["entities_deleted"] >= 1


def test_survivors_that_lost_a_source_are_reworded_from_structure(full_day):
    conn = full_day.conn
    conn.execute("UPDATE claims SET text='Me met Alex to discuss the secret proposal' WHERE"
                 " predicate='met_with'")
    conn.execute("UPDATE claim_index SET text='Me met Alex to discuss the secret proposal' WHERE"
                 " claim_id IN (SELECT claim_id FROM claims WHERE predicate='met_with')")
    gid, token = alex(full_day)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    row = conn.execute("SELECT claim_id, text FROM claims WHERE predicate='met_with'").fetchone()
    assert row["text"] == "Me met with Alex"
    assert conn.execute("SELECT COUNT(*) FROM claim_index WHERE claim_index MATCH 'secret'"
                        ).fetchone()[0] == 0
    assert receipt["kept"]["survivors_reworded"] >= 1


def test_a_summary_built_on_a_claim_that_lost_a_source_does_not_survive(full_day):
    conn = full_day.conn
    meeting = conn.execute("SELECT claim_id FROM claims WHERE predicate='summary_of' AND"
                           " status='active' AND subject_id LIKE 'episode:%1230'").fetchone()
    assert meeting
    gid, token = alex(full_day)
    engine(full_day).revoke(gid, token, run_red_team=False)
    assert conn.execute("SELECT 1 FROM claims WHERE claim_id=?", (meeting[0],)).fetchone() is None
    # a summary that never touched the conversation is left alone
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE predicate='summary_of'"
                        " AND status='active'").fetchone()[0] >= 1


# -- authentication and idempotence -----------------------------------------------------------

def test_wrong_token_changes_nothing(full_day):
    gid, token = alex(full_day)
    before = snapshot(full_day.conn)
    with pytest.raises(BadToken):
        engine(full_day).revoke(gid, token + "x")
    with pytest.raises(BadToken):
        engine(full_day).revoke(gid, "")
    assert snapshot(full_day.conn) == before
    assert full_day.conn.execute("SELECT revoked_at FROM consent_grants WHERE grant_id=?",
                                 (gid,)).fetchone()[0] is None


def test_unknown_grant(full_day):
    with pytest.raises(UnknownGrant):
        engine(full_day).revoke("grant-nope", "x")


def test_a_token_cannot_revoke_someone_elses_grant(full_day):
    other = full_day.conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='me' LIMIT 1"
                                  ).fetchone()[0]
    with pytest.raises(BadToken):
        engine(full_day).revoke(other, alex(full_day)[1])


def test_revoking_twice_is_idempotent(full_day):
    gid, token = alex(full_day)
    eng = engine(full_day)
    first = eng.revoke(gid, token, run_red_team=False)
    state = snapshot(full_day.conn)
    second = eng.revoke(gid, token, run_red_team=False)
    assert second["already_revoked"] and second["receipt_id"] == first["receipt_id"]
    assert snapshot(full_day.conn) == state
    assert full_day.conn.execute("SELECT COUNT(*) FROM forgetting_receipts").fetchone()[0] == 1


def test_revoking_a_grant_with_nothing_under_it_is_harmless(full_day):
    gid, token = create_grant(full_day.conn, SECRET, "alex", "never-used")
    before = snapshot(full_day.conn)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    assert receipt["removed"]["claims_deleted"] == 0
    assert snapshot(full_day.conn)["claims"] == before["claims"]


# -- derived state is recomputed ---------------------------------------------------------------

def _car_session(demo):
    """Put the car photo under its own grant so it can be revoked on its own."""
    create_grant(demo.conn, SECRET, "me", "car")
    gid = demo.conn.execute("SELECT grant_id FROM consent_grants WHERE scope_ref='car'"
                            ).fetchone()[0]
    cap = demo.adapter.capture(next(e for e in demo.adapter.events() if e["id"] == "F4"))
    cap.session_id = "car"
    demo.engine.ingest(cap)
    return gid


def test_removing_the_newest_sighting_brings_back_the_previous_one(played):
    gid = _car_session(played)
    conn = played.conn
    cafe = conn.execute("SELECT status FROM claims WHERE predicate='located_at' AND"
                        " event_time LIKE '%09:10%'").fetchone()
    assert cafe["status"] == "superseded"
    token = conn.execute("SELECT token_hash FROM consent_grants WHERE grant_id=?", (gid,)).fetchone()
    # mint a known token for this grant
    gid2, tok = create_grant(conn, SECRET, "me", "car2")
    conn.execute("UPDATE consent_grants SET token_hash=(SELECT token_hash FROM consent_grants"
                 " WHERE grant_id=?) WHERE grant_id=?", (gid2, gid))
    engine(played).revoke(gid, tok, run_red_team=False)
    row = conn.execute("SELECT status, superseded_by FROM claims WHERE predicate='located_at'"
                       " AND event_time LIKE '%09:10%'").fetchone()
    assert (row["status"], row["superseded_by"]) == ("active", None)
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE event_time LIKE '%17:45%'"
                        " AND predicate='located_at'").fetchone()[0] == 0


def test_a_dispute_ends_when_the_other_side_is_forgotten(played):
    conn = played.conn
    gid, tok = create_grant(conn, SECRET, "me", "desk")
    played.engine.llm.rules.append(("Desk", [claim("wallet", "located_at", "Desk",
                                                   subject_type="object", object_type="place")]))
    played.engine.ingest(RawCapture(kind="frame", session_id="desk",
                                    captured_at="2026-10-29T09:12:00",
                                    perception={"caption": "Wallet on a desk", "ocr_text": ["Desk"]}))
    statuses = {r["status"] for r in conn.execute(
        "SELECT status FROM claims WHERE predicate='located_at' AND subject_id='object:wallet'")}
    assert "disputed" in statuses
    engine(played).revoke(gid, tok, run_red_team=False)
    left = conn.execute("SELECT status FROM claims WHERE predicate='located_at' AND"
                        " subject_id='object:wallet'").fetchall()
    assert [r["status"] for r in left] == ["active"]


# -- caches, chat, files ----------------------------------------------------------------------

def _ask(demo, llm, question, answer, cited):
    llm.recall_replies[:] = [{"action": "tool", "tool": "search_claims", "args": {"query": question}},
                             {"action": "final", "status": "answered", "answer": answer,
                              "cited_claim_ids": cited, "uncertainty_note": ""}]
    return RecallService(demo.conn, llm).ask(question)


def test_cached_answers_and_chat_that_used_forgotten_claims_are_removed(full_day):
    conn, llm = full_day.conn, full_day.engine.llm
    rec = conn.execute("SELECT claim_id FROM claims WHERE predicate='recommended'").fetchone()[0]
    bb = conn.execute("SELECT claim_id FROM claims WHERE text LIKE '%Orbit%'").fetchone()[0]
    llm.rules.append(("zzz", []))
    _ask(full_day, llm, "alex recommended restaurant", "Luna Taqueria.", [rec])
    _ask(full_day, llm, "orbit fitness billboard", "It advertised Orbit Fitness.", [bb])
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 2
    gid, token = alex(full_day)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    assert receipt["removed"]["answer_cache_rows"] == 2           # derived copies: all of them go
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 0
    msgs = conn.execute("SELECT role, text, claim_ids, redacted FROM chat_messages").fetchall()
    redacted = [m for m in msgs if m["redacted"]]
    # the whole exchange goes: the answer relied on a forgotten claim, and the question itself
    # repeats a phrase that existed only in the forgotten material
    assert {m["role"] for m in redacted} == {"user", "assistant"}
    assert all(m["claim_ids"] == "[]" and "Luna" not in m["text"] for m in redacted)
    assert any("Orbit" in m["text"] for m in msgs)        # the unrelated exchange is intact
    assert receipt["removed"]["chat_messages_redacted"] == 2


def test_the_database_file_itself_forgets(tmp_path):
    path = str(tmp_path / "m.db")
    conn = db.connect(path)
    from app.capture.adapters import MockDayAdapter
    ad = MockDayAdapter(Settings().demo_script)
    llm = FakeLLM()
    demo = DemoRunner(MemoryEngine(conn, llm, ad.owner, ad.names), ad, SECRET)
    demo.advance(50)
    conn.commit()
    raw = lambda: b"".join(Path(path + s).read_bytes() for s in ("", "-wal") if Path(path + s).exists()).lower()
    assert b"al pastor" in raw() and b"proposal by friday" in raw()
    gid = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'").fetchone()[0]
    receipt = RevocationEngine(conn, SECRET, llm, db_path=path).revoke(
        gid, demo.tokens["alex:sync-alex"], run_red_team=False)
    data = raw()
    for gone in (b"al pastor", b"proposal by friday", b"green awning, best", b"promise"):
        assert gone not in data
    assert b"orbit fitness" in data                       # what stays, stays
    disk = next(p for p in receipt["probes"] if p["id"] == 7)
    assert disk["status"] == "pass" and "m.db" in disk["detail"]["files_scanned"]


def test_the_whole_runtime_model_cache_is_cleared_and_the_seed_is_never_touched(full_day, tmp_path):
    runtime, seed = tmp_path / "runtime", tmp_path / "seed"
    runtime.mkdir(); seed.mkdir()
    (runtime / "a.json").write_text(json.dumps({"claims": [{"text": "Alex said try the al pastor"}]}))
    (runtime / "b.json").write_text(json.dumps({"claims": [{"text": "A billboard advertises Orbit"}]}))
    (seed / "c.json").write_text(json.dumps({"claims": [{"text": "Alex said try the al pastor"}]}))
    gid, token = alex(full_day)
    receipt = engine(full_day, cache_dir=str(runtime)).revoke(gid, token, run_red_team=False)
    assert list(runtime.glob("*.json")) == []                 # nothing is kept: dependence is not recorded
    assert (seed / "c.json").exists()                         # read-only fixtures are never touched
    assert receipt["removed"]["model_cache_files"] == 2
    p4 = next(p for p in receipt["probes"] if p["id"] == 4)
    assert p4["status"] == "pass" and p4["detail"]["model_cache_files_remaining"] == 0


# -- the probes can actually fail -------------------------------------------------------------

@pytest.fixture
def forgotten(full_day):
    gid, token = alex(full_day)
    eng = engine(full_day)
    eng.revoke(gid, token, run_red_team=False)
    terms = distinctive_terms(
        ["Alex: You've got to try the taco place, best al pastor", "I'll send you the proposal by Friday"],
        texts(full_day.conn) + eng._structural_text())
    return full_day, terms


def test_probes_pass_on_a_clean_state(forgotten):
    demo, terms = forgotten
    assert "pastor" in terms and "proposal" in terms and "place" not in terms
    c = demo.conn
    assert probes.graph_support(c, []).status == "pass"
    assert probes.search_index(c, terms).status == "pass"
    assert probes.export(c, terms).status == "pass"
    assert probes.caches_and_chat(c, terms, None).status == "pass"


def test_search_probe_catches_a_leftover_index_row(forgotten):
    demo, terms = forgotten
    demo.conn.execute("INSERT INTO claim_index(claim_id, text) VALUES ('clm-ghost','best al pastor')")
    assert probes.search_index(demo.conn, terms).status == "fail"


def test_graph_probe_catches_an_unsupported_claim_and_a_dangling_justification(forgotten):
    demo, _ = forgotten
    c = demo.conn
    c.execute("INSERT INTO claims VALUES ('clm-x','me','said',NULL,'x',NULL,NULL,NULL,"
              "'direct_observation',0.9,NULL,'x','active',NULL,'t')")
    assert probes.graph_support(c, []).status == "fail"
    c.execute("DELETE FROM claims WHERE claim_id='clm-x'")
    src = c.execute("SELECT source_id FROM sources WHERE status='revoked' LIMIT 1").fetchone()[0]
    claim_id = c.execute("SELECT claim_id FROM claims LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO justifications VALUES ('j-bad',?, 'source', ?, NULL)", (claim_id, src))
    assert probes.graph_support(c, []).status == "fail"


def test_graph_probe_catches_a_surviving_removed_entity(forgotten):
    demo, _ = forgotten
    assert probes.graph_support(demo.conn, ["person:alex"]).status == "fail"


def test_cache_probe_catches_a_stale_answer_chat_and_model_file(forgotten, tmp_path):
    demo, terms = forgotten
    c = demo.conn
    c.execute("INSERT INTO answer_cache VALUES ('h','{\"answer\":\"try the al pastor\"}','[]')")
    c.execute("INSERT INTO chat_messages VALUES ('m1','assistant','best al pastor','[]',0)")
    (tmp_path / "x.json").write_text('{"summary": "alex promised the proposal"}')
    r = probes.caches_and_chat(c, terms, str(tmp_path))
    assert r.status == "fail"
    assert (r.detail["answer_cache_rows"], r.detail["chat_rows"],
            r.detail["model_cache_files_with_removed_text"]) == (1, 1, 1)


def test_vector_probe_catches_an_orphan_vector(forgotten):
    demo, terms = forgotten
    demo.conn.execute("INSERT INTO claim_vectors VALUES ('clm-ghost', ?)", (b"\x00" * 1024,))
    assert probes.vectors(demo.conn, ["best al pastor"], terms).status == "fail"


def test_export_probe_catches_removed_text_in_a_source(forgotten):
    demo, terms = forgotten
    demo.conn.execute("UPDATE sources SET text='Alex: best al pastor' WHERE status='active' AND"
                      " source_id=(SELECT source_id FROM sources WHERE status='active' LIMIT 1)")
    assert probes.export(demo.conn, terms).status == "fail"


def test_disk_probe_matches_whole_words_only(tmp_path):
    db_file = tmp_path / "x.db"
    db_file.write_bytes(b"CREATE TABLE t (x CHECK (x > 0)); a rechecking pastoral note")
    assert probes.disk(str(db_file), [], ["pastor"]).status == "pass"    # inside 'pastoral'
    assert probes.disk(str(db_file), [], ["check"]).status == "fail"     # a whole word


def test_disk_probe_catches_media_and_raw_text(tmp_path):
    db_file = tmp_path / "x.db"
    db_file.write_bytes(b"...Best Al Pastor...")
    (tmp_path / "leak.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    r = probes.disk(str(db_file), [str(tmp_path)], ["al pastor"])
    assert r.status == "fail" and r.detail["media_bytes"] == 104 and r.detail["raw_term_hits"] == 1


def test_red_team_probe(forgotten):
    demo, terms = forgotten
    llm = demo.engine.llm
    q = ["What did Alex say about food?", "Summarize my afternoon."]
    abstain = {"action": "final", "status": "abstained", "answer": "No record.",
               "cited_claim_ids": [], "uncertainty_note": ""}
    llm.recall_replies[:] = [abstain, abstain]
    assert probes.red_team(demo.conn, llm, q, terms).status == "pass"
    leak = {**abstain, "answer": "Alex told you about the best al pastor."}
    llm.recall_replies[:] = [leak, abstain]
    assert probes.red_team(demo.conn, llm, q, terms).status == "fail"
    assert probes.red_team(demo.conn, None, q, terms).status == "skipped"

    class Down(FakeLLM):
        def complete_json(self, *a):
            raise LLMUnavailable("no recorded response")
    r = probes.red_team(demo.conn, Down(), q, terms)
    assert r.status == "skipped" and "model unavailable" in r.detail["reason"]


def test_skipped_probes_do_not_count_as_passed(full_day):
    gid, token = alex(full_day)
    s = engine(full_day).revoke(gid, token, run_red_team=False)["summary"]
    assert (s["probes_skipped"], s["all_passed"]) == (1, False)
    assert s["probes_passed"] == 6 and s["probes_failed"] == 0


def test_all_seven_probes_pass_when_the_red_team_runs(full_day):
    llm = full_day.engine.llm
    abstain = {"action": "final", "status": "abstained", "answer": "No record.",
               "cited_claim_ids": [], "uncertainty_note": ""}
    llm.recall_replies[:] = [abstain] * 5
    gid, token = alex(full_day)
    eng = RevocationEngine(full_day.conn, SECRET, llm, red_team_questions=["q1", "q2", "q3", "q4", "q5"])
    s = eng.revoke(gid, token)["summary"]
    assert s == {"probes_passed": 7, "probes_failed": 0, "probes_skipped": 0, "probes_total": 7,
                 "all_passed": True}


# -- terms ------------------------------------------------------------------------------------

def test_terms_are_phrases_unique_to_the_removed_text():
    removed = ["Alex: try the taco place across the street, best al pastor", "send the proposal by Friday"]
    remaining = ["Me met with Alex", "Luna Taqueria has a green awning", "place type: person"]
    t = distinctive_terms(removed, remaining)
    assert {"pastor", "proposal", "friday"} <= set(t)
    assert "alex" not in t and "place" not in t           # present in what remains
    assert not any(" " in x and "pastor" in x for x in t)   # the shorter word already covers it


def test_digest_is_order_independent():
    assert digest(["b", "a"]) == digest(["a", "b"]) != digest(["a"])


# -- API --------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    llm = FakeLLM()
    c = TestClient(create_app(Settings(auth=False, db_path=":memory:", llm_mode="live", cache_dir=str(tmp_path / "seed"),
                                       runtime_cache_dir=str(tmp_path / "rt")), llm))
    c.llm = llm
    c.post("/demo/advance", params={"steps": 10})
    c.post("/demo/live/F4")
    g = {x["grantor"]: x for x in c.get("/demo/grants").json() if x["scope_ref"] == "sync-alex"}
    c.alex = g["alex"]
    return c


def test_api_revoke_flow(client):
    a = client.alex
    assert a["demo_token"] and a["revoked_at"] is None
    assert client.post(f"/consent/grants/{a['grant_id']}/revoke", json={"token": "wrong"}).status_code == 403
    assert client.post("/consent/grants/grant-none/revoke", json={"token": "x"}).status_code == 404
    assert client.post(f"/consent/grants/{a['grant_id']}/revoke", json={}).status_code == 422
    assert "recommended" in {e["predicate"] for e in client.get("/graph").json()["edges"]}
    r = client.post(f"/consent/grants/{a['grant_id']}/revoke", params={"red_team": "false"},
                    json={"token": a["demo_token"]})
    assert r.status_code == 200
    receipt = r.json()
    assert receipt["summary"]["probes_failed"] == 0 and receipt["removed"]["claims_deleted"] > 5
    preds = {e["predicate"] for e in client.get("/graph", params={"include": "history"}).json()["edges"]}
    assert not preds & {"recommended", "said", "committed_to", "same_as"}
    assert "met_with" in preds
    assert client.get(f"/receipts/{receipt['receipt_id']}").json()["receipt_id"] == receipt["receipt_id"]
    assert client.get("/receipts/none").status_code == 404
    again = client.post(f"/consent/grants/{a['grant_id']}/revoke", params={"red_team": "false"},
                        json={"token": a["demo_token"]}).json()
    assert again["already_revoked"] and again["receipt_id"] == receipt["receipt_id"]
    listed = {g["grant_id"]: g for g in client.get("/consent/grants").json()}
    assert listed[a["grant_id"]]["revoked_at"] and "token" not in json.dumps(listed)
    exported = json.dumps(client.get("/export").json()).lower()
    assert "pastor" not in exported and "proposal" not in exported and "orbit fitness" in exported


def test_forgotten_questions_cannot_be_answered_any_more(client):
    a = client.alex
    client.post(f"/consent/grants/{a['grant_id']}/revoke", params={"red_team": "false"},
                json={"token": a["demo_token"]})
    from app.recall.tools import RecallTools
    t = RecallTools(client.app.state.conn)
    for q in ("restaurant Alex recommended", "proposal by Friday", "al pastor taco", "promise"):
        hits = t.run("search_claims", {"query": q, "k": 12})
        blob = " ".join(h["text"] for h in hits).lower()
        assert "recommended luna" not in blob and "proposal" not in blob and "pastor" not in blob


# -- a recorded conversation belongs to everyone in it ----------------------------------------

def test_withdrawing_consent_removes_the_whole_recorded_conversation(full_day):
    conn = full_day.conn
    me_line = conn.execute("SELECT source_id, text FROM sources WHERE kind='transcript_segment'"
                           " AND text LIKE 'Me:%'").fetchone()
    assert me_line                                         # the owner's own half exists...
    gid, token = alex(full_day)
    receipt = engine(full_day).revoke(gid, token, run_red_team=False)
    lines = conn.execute("SELECT status, text, session_id FROM sources WHERE"
                         " kind='transcript_segment'").fetchall()
    assert len(lines) == 3 and all(r["status"] == "revoked" and r["text"] is None for r in lines)
    assert receipt["removed"]["sources_blanked"] == 3      # ...and goes with Alex's half
    assert "Sounds great" not in " | ".join(texts(conn))
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE predicate='said'").fetchone()[0] == 0
    # photos, calendar and the rest of the day are not recordings of the conversation
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE status='active'").fetchone()[0] == 5


def test_it_is_symmetric_the_owner_withdrawing_also_removes_the_conversation(full_day):
    conn = full_day.conn
    own = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='me' AND"
                       " scope_ref='sync-alex'").fetchone()[0]
    receipt = engine(full_day).revoke(own, full_day.tokens["me:sync-alex"], run_red_team=False)
    assert receipt["removed"]["sources_blanked"] == 3
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE kind='transcript_segment' AND"
                        " status='active'").fetchone()[0] == 0
    assert "Me met with Alex" in " | ".join(texts(conn))   # the calendar still stands


def test_revoking_a_session_with_no_recording_leaves_conversations_alone(full_day):
    conn = full_day.conn
    day = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='me' AND"
                       " scope_ref='day-1'").fetchone()[0]
    engine(full_day).revoke(day, full_day.tokens["me:day-1"], run_red_team=False)
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE kind='transcript_segment' AND"
                        " status='active'").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE status='active'").fetchone()[0] == 3


# -- probe precision --------------------------------------------------------------------------

def test_the_red_team_probe_ignores_words_the_asker_supplied(forgotten):
    demo, terms = forgotten
    llm = demo.engine.llm
    echo = {"action": "final", "status": "abstained", "uncertainty_note": "",
            "answer": "I have no record of what you asked about the best al pastor.",
            "cited_claim_ids": []}
    llm.recall_replies[:] = [echo]
    assert probes.red_team(demo.conn, llm, ["What is the best al pastor?"], terms).status == "pass"
    llm.recall_replies[:] = [echo]
    assert probes.red_team(demo.conn, llm, ["Tell me about lunch."], terms).status == "fail"


def test_connecting_words_alone_are_not_probe_terms():
    removed = ["Alex: across the street from the office, thanks for coming by, best al pastor"]
    remaining = ["Luna Taqueria is across a street"]
    t = distinctive_terms(removed, remaining)
    assert "across the" not in t and "the office" not in t and "for coming" not in t
    assert "pastor" in t


def test_rare_terms_need_a_word_that_exists_nowhere_else():
    from app.privacy.terms import rare_terms
    known = ["Alex met Luna Taqueria", "predicate said recommended"]
    terms = ["alex said", "alex recommended", "pastor", "best pastor", "luna taqueria"]
    assert rare_terms(terms, known) == ["pastor", "best pastor"]


def test_phrases_are_never_formed_by_the_layout_of_a_json_document():
    doc = json.dumps({"predicate": "said", "value": "value qux5", "text": "thing"})
    assert probes.contains(doc, ["said value"]) == []          # adjacent keys, not a phrase
    assert probes.contains(doc, ["value qux5"]) == ["value qux5"]   # inside one string: found
    nested = json.dumps({"edges": [{"text": "best al pastor"}, {"text": "other"}]})
    assert probes.contains(nested, ["al pastor"]) == ["al pastor"]
    assert probes.contains(nested, ["pastor other"]) == []     # across two strings: no


def test_a_phrase_split_across_two_fields_is_not_a_hit(forgotten):
    demo, _ = forgotten
    demo.conn.execute("UPDATE claims SET text='the best', object_value='al pastor' WHERE"
                      " claim_id=(SELECT claim_id FROM claims LIMIT 1)")
    assert probes.search_index(demo.conn, ["best al"]).detail["text_scan_hits"] == 0
    demo.conn.execute("UPDATE claims SET text='the best al pastor' WHERE claim_id=("
                      "SELECT claim_id FROM claims LIMIT 1)")
    assert probes.search_index(demo.conn, ["best al"]).detail["text_scan_hits"] == 1


def test_the_grants_list_says_which_receipt_belongs_to_a_revoked_grant(client):
    a = client.alex
    before = {g["grant_id"]: g for g in client.get("/consent/grants").json()}
    assert all(g["receipt_id"] is None for g in before.values())
    receipt = client.post(f"/consent/grants/{a['grant_id']}/revoke", params={"red_team": "false"},
                          json={"token": a["demo_token"]}).json()
    after = {g["grant_id"]: g for g in client.get("/consent/grants").json()}
    assert after[a["grant_id"]]["receipt_id"] == receipt["receipt_id"]
    assert after[a["grant_id"]]["revoked_at"]
    assert [g for g in after.values() if g["grant_id"] != a["grant_id"] and g["receipt_id"]] == []
