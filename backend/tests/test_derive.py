from datetime import datetime

import pytest

from app.capture.models import RawCapture
from app.compiler.derive import attrs_agree, parse_attr
from app.graph import build_graph
from app.privacy.filter import authorized_claim_ids, visible_claim_ids

from .fakes import FakeLLM, claim


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def claims(conn, predicate, **where):
    clause = "".join(f" AND {k}=?" for k in where)
    return conn.execute(f"SELECT * FROM claims WHERE predicate=?{clause}",
                        (predicate, *where.values())).fetchall()


def premises_of(conn, claim_id):
    return {r[0] for r in conn.execute(
        "SELECT p.premise_claim_id FROM justification_premises p JOIN justifications j"
        " USING(justification_id) WHERE j.claim_id=?", (claim_id,))}


# -- attribute matching -----------------------------------------------------------------------

def test_attribute_parsing_and_agreement():
    assert parse_attr("Awning: Green") == ("awning", "green")
    assert parse_attr("no colon") is None
    green = [("awning", "green")]
    assert attrs_agree(green, [("awning", "bright green"), ("kind", "taco")])
    assert not attrs_agree(green, [("awning", "blue")])          # conflict
    assert not attrs_agree(green, [("kind", "taco")])            # nothing in common


# -- spatial referent resolution --------------------------------------------------------------

def test_taco_place_is_bound_to_luna_and_recommended(played):
    conn = played.conn
    (rec,) = claims(conn, "recommended")
    assert (rec["subject_id"], rec["object_id"]) == ("person:alex", "place:luna-taqueria")
    assert rec["evidence_type"] == "inference"
    (same,) = claims(conn, "same_as")
    assert same["subject_id"] == "place:luna-taqueria" and same["object_value"] == "taco place"
    prem = premises_of(conn, rec["claim_id"])
    texts = {one(conn, "SELECT text FROM claims WHERE claim_id=?", p)[0] for p in prem}
    assert any("across the street" in t for t in texts)             # the description
    assert any("green awning" in t for t in texts)                  # both attribute claims
    assert any("Alex said" in t for t in texts)                     # the utterance
    assert any("Luna Taqueria has a green awning" in t for t in texts)   # the sign
    low = min(one(conn, "SELECT confidence FROM claims WHERE claim_id=?", p)[0] for p in prem)
    assert rec["confidence"] == round(low * 0.9, 3)                 # inference = min(premises) x 0.9
    j = one(conn, "SELECT kind, rule, source_id FROM justifications WHERE claim_id=?",
            rec["claim_id"])
    assert (j["kind"], j["rule"], j["source_id"]) == ("derivation", "spatial_referent_resolution", None)


def test_binding_is_idempotent_on_replay(played):
    before = one(played.conn, "SELECT COUNT(*) FROM claims")[0]
    for ev in played._scheduled():
        played.play(ev["id"])
    assert one(played.conn, "SELECT COUNT(*) FROM claims")[0] == before
    assert len(claims(played.conn, "recommended")) == 1


def test_model_can_decline_the_binding(conn, adapter):
    from app.demo import DemoRunner
    from app.engine import MemoryEngine
    llm = FakeLLM()
    llm.bind = False
    d = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, "s")
    d.advance(50)
    assert claims(conn, "recommended") == [] and llm.bind_requests


def test_nothing_is_proposed_when_the_place_is_too_far(demo, fake):
    demo.advance(3)                        # F1, F2, C1
    demo.play("A1")
    cap = demo.adapter.capture(next(e for e in demo.adapter.events() if e["id"] == "F3"))
    cap.lat += 0.01                        # about 1.1 km away: not across the street
    demo.engine.ingest(cap)
    assert fake.bind_requests == [] and claims(demo.conn, "recommended") == []


def test_conflicting_attribute_blocks_the_binding(demo, fake):
    demo.advance(3)
    demo.play("A1")
    cap = demo.adapter.capture(next(e for e in demo.adapter.events() if e["id"] == "F3"))
    cap.perception = {**cap.perception, "objects": [{"label": "awning", "attrs": {"color": "blue"}}]}
    fake.rules = [(k, ([claim("Luna Taqueria", "has_attribute", subject_type="place",
                              value="awning: blue")] if k == "Luna Taqueria" else v))
                  for k, v in fake.rules]
    demo.engine.ingest(cap)
    assert fake.bind_requests == [] and claims(demo.conn, "recommended") == []


def test_model_cannot_pick_a_non_candidate(conn, adapter):
    from app.demo import DemoRunner
    from app.engine import MemoryEngine

    class Rogue(FakeLLM):
        def complete_json(self, system, user, schema):
            if system.startswith("A spoken conversation"):
                return {"match": "place:blue-door-cafe"}
            return super().complete_json(system, user, schema)

    d = DemoRunner(MemoryEngine(conn, Rogue(), adapter.owner, adapter.names), adapter, "s")
    d.advance(50)
    assert claims(conn, "recommended") == [] and claims(conn, "same_as") == []


def test_future_mentions_of_the_alias_resolve_to_luna(played):
    r = played.engine.compiler.resolver
    assert r.resolve("the taco place", "place", "x")[0] == "place:luna-taqueria"


# -- last_seen / supersession -----------------------------------------------------------------

def test_late_upload_is_ordered_by_event_time_not_arrival(demo):
    demo.advance(50)
    demo.play("F4")                                         # 17:45 arrives first...
    demo.engine.ingest(RawCapture(                           # ...then an older 11:00 sighting
        kind="frame", session_id="day-1", captured_at="2026-10-29T11:00:00",
        perception={"caption": "A wallet on a desk", "ocr_text": ["Desk"], "objects": []}))
    demo.engine.compiler.deriver.supersede_located_at({"object:wallet"})
    rows = {r["event_time"][11:16]: r["status"] for r in claims(demo.conn, "located_at")}
    assert rows["17:45"] == "active" and rows["09:10"] == "superseded"


def test_supersession_is_reversible_when_the_newer_sighting_goes_away(full_day):
    conn = full_day.conn
    conn.execute("UPDATE claims SET status='revoked' WHERE predicate='located_at'"
                 " AND event_time LIKE '%17:45%'")
    full_day.engine.compiler.deriver.supersede_located_at({"object:wallet"})
    cafe = one(conn, "SELECT status FROM claims WHERE event_time LIKE '%09:10%' AND"
                     " predicate='located_at'")
    assert cafe["status"] == "active"


# -- episode summary --------------------------------------------------------------------------

def test_summary_is_a_claim_that_cites_its_premises(played):
    conn = played.conn
    rows = claims(conn, "summary_of", status="active")
    assert rows and all(premises_of(conn, r["claim_id"]) for r in rows)
    meeting = one(conn, "SELECT claim_id FROM claims WHERE predicate='summary_of' AND"
                        " subject_id LIKE 'episode:%1230%' AND status='active'")
    prem = premises_of(conn, meeting["claim_id"])
    assert one(conn, "SELECT claim_id FROM claims WHERE predicate='said'")["claim_id"] in prem
    assert not any(one(conn, "SELECT predicate FROM claims WHERE claim_id=?", p)[0]
                   in ("summary_of", "part_of_episode", "same_as") for p in prem)


def test_a_new_claim_retires_the_old_summary(played):
    conn = played.conn
    ep = "episode:20261029-1230"
    old = one(conn, "SELECT claim_id FROM claims WHERE subject_id=? AND predicate='summary_of'"
                    " AND status='active'", ep)["claim_id"]
    played.engine.llm.rules.append(("hi again", [claim("Alex", "said", value="hi again")]))
    played.engine.ingest(RawCapture(kind="note", session_id="day-1",
                                    captured_at="2026-10-29T13:00:00", text="Alex said hi again"))
    new = one(conn, "SELECT claim_id FROM claims WHERE subject_id=? AND predicate='summary_of'"
                    " AND status='active'", ep)["claim_id"]
    assert new != old
    assert one(conn, "SELECT status, superseded_by FROM claims WHERE claim_id=?", old)[:] == \
        ("superseded", new)
    assert one(conn, "SELECT COUNT(*) FROM claims WHERE subject_id=? AND predicate='summary_of'"
                     " AND status='active'", ep)[0] == 1


def test_unchanged_premises_keep_the_same_summary(played):
    conn = played.conn
    ep = "episode:20261029-1230"
    n = one(conn, "SELECT COUNT(*) FROM claims WHERE subject_id=? AND predicate='summary_of'", ep)[0]
    played.engine.compiler.deriver.summarize_episode(ep, __import__(
        "app.compiler.derive", fromlist=["DeriveResult"]).DeriveResult())
    assert one(conn, "SELECT COUNT(*) FROM claims WHERE subject_id=? AND predicate='summary_of'",
               ep)[0] == n


# -- privacy filter: derived claims depend on ALL premises ------------------------------------

def test_withdrawing_alex_consent_removes_what_only_the_conversation_supported(played):
    conn = played.conn
    (rec,) = claims(conn, "recommended")
    (said,) = claims(conn, "said", subject_id="person:alex")
    (met,) = claims(conn, "met_with")
    luna_awning = one(conn, "SELECT claim_id FROM claims WHERE subject_id='place:luna-taqueria'"
                            " AND predicate='has_attribute' AND object_value LIKE 'awning%'")[0]
    assert {rec["claim_id"], said["claim_id"], met["claim_id"], luna_awning} <= \
        authorized_claim_ids(conn)
    conn.execute("UPDATE consent_grants SET revoked_at='2026-10-29T14:00:00' WHERE grantor='alex'")
    ok = authorized_claim_ids(conn)
    assert rec["claim_id"] not in ok and said["claim_id"] not in ok      # only the talk supported them
    assert met["claim_id"] in ok                                          # the calendar still does
    assert luna_awning in ok                                              # the sign still does


def test_cyclic_derivations_cannot_keep_each_other_alive(conn):
    conn.execute("INSERT INTO entities VALUES ('e','object','x',NULL)")
    for c in ("a", "b"):
        conn.execute("INSERT INTO claims VALUES (?, 'e','has_attribute',NULL,'v',NULL,NULL,NULL,"
                     "'inference',0.5,NULL,'t','active',NULL,'t')", (c,))
    for j, (cid, prem) in enumerate([("a", "b"), ("b", "a")]):
        conn.execute("INSERT INTO justifications VALUES (?,?, 'derivation', NULL, 'r')",
                     (f"j{j}", cid))
        conn.execute("INSERT INTO justification_premises VALUES (?,?)", (f"j{j}", prem))
    assert authorized_claim_ids(conn) == set()


def test_visible_claims_respect_history_flag(full_day):
    conn = full_day.conn
    cafe = one(conn, "SELECT claim_id FROM claims WHERE predicate='located_at' AND"
                     " status='superseded'")[0]
    assert cafe not in visible_claim_ids(conn)
    assert cafe in visible_claim_ids(conn, include_history=True)
    assert any(e["status"] == "superseded" for e in
               build_graph(conn, include_history=True)["edges"])
