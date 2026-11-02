"""Regressions for the independent Phase 3 review (four consent and retention defects).

Each test states the promise that was broken: forgetting must follow who actually consented,
must reach every store that can hold what was forgotten, and must not leave metadata behind.
"""
import json

import pytest

from app import db
from app.capture.models import RawCapture
from app.engine import MemoryEngine
from app.graph import build_graph
from app.privacy import probes
from app.privacy.consent import create_grant
from app.privacy.filter import authorized_claim_ids, valid_source_ids
from app.privacy.revocation import RevocationEngine

from .fakes import FakeLLM, claim

SECRET = "review-secret"


class World:
    """A small database, a scripted model, and helpers to give consent and capture things."""

    def __init__(self, rules=None, cache_dir=None):
        self.conn = db.connect()
        self.llm = FakeLLM(rules=rules or [])
        self.engine = MemoryEngine(self.conn, self.llm, "me", {"me": "Me", "alex": "Alex", "bob": "Bob"})
        self.revoker = RevocationEngine(self.conn, SECRET, self.llm, cache_dir=cache_dir)
        self.tokens: dict[str, str] = {}

    def grant(self, grantor: str, session: str) -> str:
        gid, tok = create_grant(self.conn, SECRET, grantor, session)
        self.tokens[gid] = tok
        return gid

    def note(self, session: str, at: str, text: str, **kw):
        return self.engine.ingest(RawCapture(kind="note", session_id=session, captured_at=at, text=text, **kw))

    def talk(self, session: str, at: str, who: list[str], lines: list[tuple[str, str]]):
        speakers = {"me": "A", "alex": "B", "bob": "B"}
        turns = [{"turn_id": i, "start_ms": i * 1000, "end_ms": i * 1000 + 500, "speaker": speakers[p], "text": t}
                 for i, (p, t) in enumerate(lines, 1)]
        return self.engine.ingest(RawCapture(
            kind="audio", session_id=session, captured_at=at, participants=who,
            speaker_map={"A": "me", "B": next(p for p in who if p != "me")}, turns=turns))

    def revoke(self, gid: str):
        return self.revoker.revoke(gid, self.tokens[gid], run_red_team=False)

    def active(self, kind="transcript_segment") -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sources WHERE kind=? AND status='active'", (kind,)).fetchone()[0]


# ------------------------------------------------------------------------------------------
# 1. Forgetting follows who actually consented
# ------------------------------------------------------------------------------------------

def conversation_world():
    w = World(rules=[("budget", [claim("Alex", "said", value="the budget is final", text="Alex said the budget is final")])])
    g_me, g_alex = w.grant("me", "room"), w.grant("alex", "room")
    w.talk("room", "2026-10-29T12:00:00", ["me", "alex"], [("alex", "The budget is final"), ("me", "Understood")])
    return w, g_me, g_alex


def test_each_recorded_line_remembers_every_grant_that_allowed_it():
    w, g_me, g_alex = conversation_world()
    rows = w.conn.execute("SELECT source_id FROM sources WHERE kind='transcript_segment'").fetchall()
    assert len(rows) == 2
    for r in rows:
        granted = {x[0] for x in w.conn.execute("SELECT grant_id FROM source_consents WHERE source_id=?", (r[0],))}
        assert granted == {g_me, g_alex}


def test_a_note_remembers_the_single_grant_that_allowed_it():
    w = World()
    g = w.grant("me", "s1")
    w.note("s1", "2026-10-29T10:00:00", "hello there")
    (sid,) = [r[0] for r in w.conn.execute("SELECT source_id FROM sources")]
    assert [x[0] for x in w.conn.execute("SELECT grant_id FROM source_consents WHERE source_id=?", (sid,))] == [g]


def test_an_unrelated_grant_cannot_erase_a_recording_it_took_no_part_in():
    w, g_me, g_alex = conversation_world()
    mallory = w.grant("mallory", "room")              # same session id, but never part of the recording
    receipt = w.revoke(mallory)
    assert w.active() == 2 and receipt["removed"]["sources_blanked"] == 0
    assert w.conn.execute("SELECT COUNT(*) FROM claims WHERE predicate='said'").fetchone()[0] == 1


def test_an_unused_duplicate_grant_by_a_participant_authorised_nothing():
    w, g_me, g_alex = conversation_world()
    second = w.grant("alex", "room")                  # Alex signs again; the recording used the first grant
    assert w.revoke(second)["removed"]["sources_blanked"] == 0
    assert w.active() == 2
    assert w.revoke(g_alex)["removed"]["sources_blanked"] == 2   # the grant it really used removes it


def test_withdrawing_a_real_participant_removes_the_whole_recording_for_everyone():
    w, g_me, g_alex = conversation_world()
    receipt = w.revoke(g_alex)
    assert receipt["removed"]["sources_blanked"] == 2 and w.active() == 0   # including the owner's own line
    assert w.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


def test_recordings_that_share_a_session_are_removed_only_when_their_own_people_withdraw():
    w = World()
    g_me, g_alex, g_bob = w.grant("me", "room"), w.grant("alex", "room"), w.grant("bob", "room")
    w.talk("room", "2026-10-29T09:00:00", ["me", "alex"], [("alex", "first recording")])
    w.talk("room", "2026-10-29T15:00:00", ["me", "bob"], [("bob", "second recording")])
    assert w.active() == 2
    w.revoke(g_alex)                                  # only the first recording needed Alex
    texts = [r[0] for r in w.conn.execute("SELECT text FROM sources WHERE status='active'")]
    assert texts == ["Bob: second recording"]
    w.revoke(g_me)                                    # both recordings needed the owner
    assert w.active() == 0


def test_a_source_is_unusable_the_moment_any_grant_it_needs_is_revoked(tmp_path):
    """Defence in depth: even before the purge runs, the filter refuses it."""
    w, g_me, g_alex = conversation_world()
    assert len(valid_source_ids(w.conn)) == 2
    w.conn.execute("UPDATE consent_grants SET revoked_at='2026-10-29T13:00:00' WHERE grant_id=?", (g_alex,))
    assert valid_source_ids(w.conn) == set()
    assert not authorized_claim_ids(w.conn)


def test_sources_without_consent_rows_fall_back_to_their_own_grant():
    """Rows written before the table existed still behave as before."""
    w = World()
    g = w.grant("me", "s1")
    w.conn.execute("INSERT INTO sources(source_id, kind, session_id, grant_id, captured_at, ingested_at, text,"
                   " content_hash) VALUES ('old','user_confirmation','s1',?, '2026-10-29T10:00:00','t','x','h')", (g,))
    assert "old" in valid_source_ids(w.conn)
    w.conn.execute("UPDATE consent_grants SET revoked_at='t' WHERE grant_id=?", (g,))
    assert "old" not in valid_source_ids(w.conn)


# ------------------------------------------------------------------------------------------
# 2. Cached model output is cleared by provenance, not by guessing phrases
# ------------------------------------------------------------------------------------------

def pin_world(tmp_path):
    cache = tmp_path / "runtime"
    cache.mkdir()
    w = World(rules=[("PIN", [claim("Me", "said", value="PIN is 1234", text="Me said PIN is 1234")])], cache_dir=str(cache))
    g = w.grant("me", "s1")
    w.note("s1", "2026-10-29T10:00:00", "My PIN is 1234")
    return w, g, cache


def test_a_short_numeric_secret_does_not_survive_in_the_runtime_model_cache(tmp_path):
    w, g, cache = pin_world(tmp_path)
    (cache / "reply.json").write_text(json.dumps({"claims": [{"text": "Me said PIN is 1234"}]}))
    receipt = w.revoke(g)
    assert not (cache / "reply.json").exists()
    assert receipt["removed"]["model_cache_files"] == 1
    p4 = next(p for p in receipt["probes"] if p["id"] == 4)
    assert p4["status"] == "pass" and p4["detail"]["model_cache_files_remaining"] == 0


def test_every_runtime_cache_entry_goes_but_the_read_only_seed_is_untouched(tmp_path):
    w, g, cache = pin_world(tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "fixture.json").write_text("{}")
    for n in ("a", "b", "c"):
        (cache / f"{n}.json").write_text(json.dumps({"summary": f"unrelated {n}"}))
    assert w.revoke(g)["removed"]["model_cache_files"] == 3
    assert list(cache.glob("*.json")) == [] and (seed / "fixture.json").exists()


def test_the_cache_probe_fails_if_any_runtime_entry_is_left(tmp_path):
    w, g, cache = pin_world(tmp_path)
    w.revoke(g)
    (cache / "late.json").write_text("{}")
    assert probes.caches_and_chat(w.conn, [], str(cache)).status == "fail"


def test_answer_cache_is_cleared_whole_because_it_is_only_a_derived_copy(tmp_path):
    w, g, cache = pin_world(tmp_path)
    w.conn.execute("INSERT INTO answer_cache VALUES ('h1', ?, '[]')", (json.dumps({"answer": "it is 1234"}),))
    w.conn.execute("INSERT INTO answer_cache VALUES ('h2', ?, '[]')", (json.dumps({"answer": "unrelated"}),))
    assert w.revoke(g)["removed"]["answer_cache_rows"] == 2
    assert w.conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------
# 3. A receipt is a memory store too
# ------------------------------------------------------------------------------------------

def shared_fact_world():
    w = World(rules=[("Zephyr", [claim("Me", "said", value="Project Zephyr launches in May",
                                       text="Me said Project Zephyr launches in May")])])
    ga, gb = w.grant("me", "A"), w.grant("me", "B")
    for s in ("A", "B"):
        w.note(s, "2026-10-29T10:00:00", f"Project Zephyr launches in May ({s})")
    assert w.conn.execute("SELECT COUNT(*) FROM justifications").fetchone()[0] >= 2
    return w, ga, gb


def test_stored_receipts_do_not_contain_claim_text():
    w, ga, gb = shared_fact_world()
    first = w.revoke(ga)
    stored = json.loads(w.conn.execute("SELECT report_json FROM forgetting_receipts WHERE receipt_id=?",
                                       (first["receipt_id"],)).fetchone()[0])
    assert all("text" not in r for r in stored["retained"])
    assert "Zephyr" not in json.dumps(stored)


def test_a_receipt_shows_a_kept_fact_while_it_is_kept_and_says_so_once_it_is_forgotten():
    w, ga, gb = shared_fact_world()
    first = w.revoke(ga)
    kept = [r for r in first["retained"] if r["predicate"] == "said"]
    assert kept and "Zephyr" in kept[0]["text"]                       # readable now
    w.revoke(gb)                                                      # the last support goes
    again = w.revoker.get_receipt(first["receipt_id"])
    assert "Zephyr" not in json.dumps(again)                          # nothing forgotten is echoed back
    assert [r["text"] for r in again["retained"] if r["predicate"] == "said"] == ["[forgotten since]"]


def test_old_receipts_that_already_hold_text_are_scrubbed_by_the_next_revocation():
    w, ga, gb = shared_fact_world()
    first = w.revoke(ga)
    legacy = json.loads(w.conn.execute("SELECT report_json FROM forgetting_receipts WHERE receipt_id=?",
                                       (first["receipt_id"],)).fetchone()[0])
    legacy["retained"][0]["text"] = "Project Zephyr launches in May"      # as the first version stored it
    w.conn.execute("UPDATE forgetting_receipts SET report_json=? WHERE receipt_id=?",
                   (json.dumps(legacy), first["receipt_id"]))
    w.revoke(gb)
    raw = w.conn.execute("SELECT report_json FROM forgetting_receipts WHERE receipt_id=?", (first["receipt_id"],)).fetchone()[0]
    assert "Zephyr" not in raw


def test_receipts_are_checked_by_the_cache_probe():
    w, ga, gb = shared_fact_world()
    first = w.revoke(ga)
    w.conn.execute("UPDATE forgetting_receipts SET report_json=? WHERE receipt_id=?",
                   (json.dumps({"retained": [{"text": "leaked zephyr"}]}), first["receipt_id"]))
    assert probes.caches_and_chat(w.conn, ["zephyr"], None).status == "fail"


def test_asking_again_to_forget_returns_the_same_receipt_with_current_text():
    w, ga, gb = shared_fact_world()
    first = w.revoke(ga)
    again = w.revoke(ga)
    assert again["already_revoked"] and again["receipt_id"] == first["receipt_id"]
    assert [r["text"] for r in again["retained"] if r["predicate"] == "said"] == [r["text"] for r in first["retained"] if r["predicate"] == "said"]


# ------------------------------------------------------------------------------------------
# 4. Metadata that only a revoked source supplied goes with it
# ------------------------------------------------------------------------------------------

def episode_world():
    shared = claim("Me", "observed_at", "Spot", object_type="place", text="Me was at Spot")
    w = World(rules=[("thing one", [shared, claim("thing one", "located_at", "Spot", subject_type="object", object_type="place")]),
                     ("thing two", [shared, claim("thing two", "located_at", "Spot", subject_type="object", object_type="place")])])
    ga, gb = w.grant("me", "A"), w.grant("me", "B")
    w.note("A", "2026-10-29T10:00:00", "thing one", lat=37.1234, lon=-122.5678)
    w.note("B", "2026-10-29T10:10:00", "thing two")
    assert w.conn.execute("SELECT COUNT(*) FROM entities WHERE type='episode'").fetchone()[0] == 1
    return w, ga, gb


def episode_nodes(w):
    return [n for n in build_graph(w.conn, include_history=True)["nodes"] if n["type"] == "episode"]


def test_an_episode_forgets_the_location_and_time_that_only_a_revoked_source_supplied():
    w, ga, gb = episode_world()
    w.revoke(ga)
    (ep,) = episode_nodes(w)
    assert ep["attrs"]["lat"] is None and ep["attrs"]["lon"] is None
    assert ep["attrs"]["start"] == "2026-10-29T10:10:00" and ep["attrs"]["end"] == "2026-10-29T10:10:00"
    assert ep["name"] == "Episode 10:10"


def test_the_episode_id_does_not_keep_the_revoked_sources_time():
    w, ga, gb = episode_world()
    old = episode_nodes(w)[0]["id"]
    assert "1000" in old
    w.revoke(ga)
    (ep,) = episode_nodes(w)
    assert ep["id"] != old and "1000" not in ep["id"] and ep["id"].endswith("1010")
    # everything that pointed at the episode follows it
    assert w.conn.execute("SELECT COUNT(*) FROM claims WHERE episode_id=?", (old,)).fetchone()[0] == 0
    assert w.conn.execute("SELECT COUNT(*) FROM claims WHERE episode_id=?", (ep["id"],)).fetchone()[0] > 0
    assert w.conn.execute("SELECT COUNT(*) FROM claims WHERE object_id=?", (old,)).fetchone()[0] == 0


def test_wording_that_quoted_the_old_time_bounds_is_rewritten():
    w, ga, gb = episode_world()
    assert any("10:00-10:10" in r[0] for r in w.conn.execute("SELECT text FROM claims"))
    w.revoke(ga)
    assert not any("10:00" in r[0] for r in w.conn.execute("SELECT text FROM claims"))
    assert not any("10:00" in r[0] for r in w.conn.execute("SELECT text FROM claim_index"))


def test_a_claim_two_sources_stated_drops_the_time_the_revoked_one_gave_it():
    w, ga, gb = episode_world()
    (before,) = w.conn.execute("SELECT event_time FROM claims WHERE predicate='observed_at'").fetchone()
    assert before == "2026-10-29T10:00:00"              # the first writer's time
    w.revoke(ga)
    (after,) = w.conn.execute("SELECT event_time FROM claims WHERE predicate='observed_at'").fetchone()
    assert after == "2026-10-29T10:10:00"


def test_revoking_the_later_source_keeps_the_earlier_bounds():
    w, ga, gb = episode_world()
    w.revoke(gb)
    (ep,) = episode_nodes(w)
    assert ep["attrs"]["lat"] == 37.1234 and ep["attrs"]["start"] == "2026-10-29T10:00:00" and ep["attrs"]["end"] == "2026-10-29T10:00:00"


def test_an_episode_nothing_supports_any_more_is_removed():
    w, ga, gb = episode_world()
    w.revoke(ga)
    w.revoke(gb)
    assert episode_nodes(w) == []
    assert w.conn.execute("SELECT COUNT(*) FROM entities WHERE type='episode'").fetchone()[0] == 0


def test_the_graph_does_not_expose_the_internal_provenance_list():
    w, ga, gb = episode_world()
    (ep,) = episode_nodes(w)
    assert "contrib" not in ep["attrs"]


def test_the_graph_probe_catches_episode_metadata_from_a_revoked_source():
    w, ga, gb = episode_world()
    w.revoke(ga)
    (eid,) = [r[0] for r in w.conn.execute("SELECT entity_id FROM entities WHERE type='episode'")]
    attrs = json.loads(w.conn.execute("SELECT attrs FROM entities WHERE entity_id=?", (eid,)).fetchone()[0])
    attrs["contrib"].append({"source_id": next(r[0] for r in w.conn.execute("SELECT source_id FROM sources WHERE status='revoked'")),
                             "start": "2026-10-29T10:00:00", "end": "2026-10-29T10:00:00", "lat": 37.1234, "lon": -122.5678})
    w.conn.execute("UPDATE entities SET attrs=? WHERE entity_id=?", (json.dumps(attrs), eid))
    result = probes.graph_support(w.conn, [])
    assert result.status == "fail" and result.detail["episode_metadata_from_removed_sources"] >= 1


# ------------------------------------------------------------------------------------------
# 5. Databases written before these fixes are upgraded, not trusted
# ------------------------------------------------------------------------------------------

from app import migrate  # noqa: E402


def as_written_before(w):
    """Put a database back into the shape the first release left it: no consent rows, and
    episodes that carry only their bounds."""
    w.conn.execute("DELETE FROM source_consents")
    for e in w.conn.execute("SELECT entity_id, attrs FROM entities WHERE type='episode'").fetchall():
        a = json.loads(e["attrs"])
        a.pop("contrib", None)
        w.conn.execute("UPDATE entities SET attrs=? WHERE entity_id=?", (json.dumps(a), e["entity_id"]))
    w.conn.commit()


def test_upgrade_ties_every_line_of_an_old_recording_to_all_its_participants():
    w, g_me, g_alex = conversation_world()
    as_written_before(w)
    assert migrate.backfill_source_consents(w.conn) == 2
    for (sid,) in w.conn.execute("SELECT source_id FROM sources").fetchall():
        granted = {x[0] for x in w.conn.execute("SELECT grant_id FROM source_consents WHERE source_id=?", (sid,))}
        assert granted == {g_me, g_alex}
    assert migrate.backfill_source_consents(w.conn) == 0            # idempotent


def test_after_upgrade_an_old_recording_disappears_when_the_other_participant_withdraws():
    w, g_me, g_alex = conversation_world()
    as_written_before(w)
    migrate.upgrade(w.conn)
    receipt = w.revoke(g_alex)
    assert receipt["removed"]["sources_blanked"] == 2 and w.active() == 0   # the owner's lines too
    assert w.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


def test_upgrade_leaves_notes_on_their_own_grant_only():
    w = World()
    g, other = w.grant("me", "s1"), w.grant("alex", "s1")
    w.note("s1", "2026-10-29T10:00:00", "hello there")
    w.conn.execute("DELETE FROM source_consents")
    migrate.upgrade(w.conn)
    assert [x[0] for x in w.conn.execute("SELECT grant_id FROM source_consents")] == [g]


def test_connecting_to_an_old_database_file_upgrades_it(tmp_path):
    path = str(tmp_path / "old.db")
    conn = db.connect(path)
    conn.execute("INSERT INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes, token_hash, granted_at)"
                 " VALUES ('g1','me','capture_session','s','[\"personal_recall\"]','h','t'),"
                 "        ('g2','alex','capture_session','s','[\"personal_recall\"]','h','t')")
    conn.execute("INSERT INTO sources(source_id, kind, session_id, grant_id, captured_at, ingested_at, text, content_hash)"
                 " VALUES ('old','transcript_segment','s','g1','2026-10-29T10:00:00','t','Me: hi','h')")
    conn.commit()
    conn.close()
    again = db.connect(path)
    assert {r[0] for r in again.execute("SELECT grant_id FROM source_consents WHERE source_id='old'")} == {"g1", "g2"}


def test_an_old_episode_forgets_revoked_location_and_time_even_though_it_had_no_provenance():
    w, ga, gb = episode_world()
    as_written_before(w)                                # the revocation below meets a legacy episode
    w.revoke(ga)
    (ep,) = episode_nodes(w)
    assert ep["attrs"]["lat"] is None and ep["attrs"]["start"] == "2026-10-29T10:10:00"
    assert ep["name"] == "Episode 10:10" and ep["id"].endswith("1010")
    assert not any("10:00" in r[0] for r in w.conn.execute("SELECT text FROM claims"))


def test_upgrade_gives_old_episodes_a_provenance_list_built_from_their_sources():
    w, ga, gb = episode_world()
    as_written_before(w)
    assert migrate.backfill_episode_provenance(w.conn) == 1
    (e,) = w.conn.execute("SELECT attrs FROM entities WHERE type='episode'").fetchall()
    contrib = json.loads(e[0])["contrib"]
    assert sorted(c["start"] for c in contrib) == ["2026-10-29T10:00:00", "2026-10-29T10:10:00"]
    assert any(c["lat"] == 37.1234 for c in contrib)
    assert migrate.backfill_episode_provenance(w.conn) == 0


def test_metadata_left_behind_by_an_earlier_version_is_corrected_by_the_next_forgetting():
    """An old revocation already ran and left the first source's place and time on the episode."""
    w, ga, gb = episode_world()
    w.revoke(ga)
    (eid,) = [r[0] for r in w.conn.execute("SELECT entity_id FROM entities WHERE type='episode'")]
    stale = {"start": "2026-10-29T10:00:00", "end": "2026-10-29T10:10:00", "lat": 37.1234, "lon": -122.5678}
    w.conn.execute("UPDATE entities SET attrs=? WHERE entity_id=?", (json.dumps(stale), eid))
    migrate.upgrade(w.conn)
    assert probes.graph_support(w.conn, []).status == "fail"        # never a quiet pass
    gc = w.grant("me", "C")
    w.note("C", "2026-10-29T15:00:00", "unrelated")
    w.revoke(gc)                                                    # any later forgetting repairs it
    (ep,) = [n for n in episode_nodes(w)]
    assert ep["attrs"]["lat"] is None and ep["attrs"]["start"] == "2026-10-29T10:10:00"
    assert probes.graph_support(w.conn, []).status == "pass"


def test_the_graph_probe_never_passes_an_episode_with_no_provenance():
    w, ga, gb = episode_world()
    as_written_before(w)
    result = probes.graph_support(w.conn, [])
    assert result.status == "fail" and result.detail["episode_metadata_from_removed_sources"] == 1


def test_a_calendar_events_end_time_survives_the_rebuild():
    rule = [claim("Me", "attended", "Standup", object_type="org", text="Me attended Standup")]
    w = World(rules=[("Standup", rule)])
    w.grant("me", "s1")
    w.engine.ingest(RawCapture(kind="calendar", session_id="s1", captured_at="2026-10-29T09:00:00",
                               ends_at="2026-10-29T09:45:00", text="Standup"))
    as_written_before(w)
    migrate.upgrade(w.conn)
    (e,) = w.conn.execute("SELECT attrs FROM entities WHERE type='episode'").fetchall()
    (c,) = json.loads(e[0])["contrib"]
    assert c["start"] == "2026-10-29T09:00:00" and c["end"] == "2026-10-29T09:45:00"


def test_an_episode_whose_only_source_produced_no_claims_is_removed_with_that_source():
    w = World()                                         # the model extracts nothing from this note
    g = w.grant("me", "s1")
    w.note("s1", "2026-10-29T15:00:00", "just a place", lat=37.1, lon=-122.5)
    assert w.conn.execute("SELECT COUNT(*) FROM entities WHERE type='episode'").fetchone()[0] == 1
    w.revoke(g)
    assert w.conn.execute("SELECT COUNT(*) FROM entities WHERE type='episode'").fetchone()[0] == 0
    assert probes.graph_support(w.conn, []).status == "pass"
