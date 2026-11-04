"""Delete one memory: forget a single saved memory (and the facts that rest only on it) without ending the whole day's
consent, with the same receipt and leak checks as a withdrawal."""
from .fakes import FakeLLM
from .test_upload_api import b64, commit, make, png
from .test_video_reading import ManyObjects, video_body


def save_note(c, text, day="2026-11-04"):
    d = c.post("/capture/preview", json={"kind": "note", "text": text, "file_modified_at": f"{day}T12:00:00"}).json()
    r = commit(c, d)
    assert r.status_code == 200, r.text
    return next(x["source_id"] for x in r.json()["results"] if x["source_id"])


def conn(c):
    return c.app.state.conn


def status(c, source_id):
    return conn(c).execute("SELECT status FROM sources WHERE source_id=?", (source_id,)).fetchone()[0]


def test_deleting_a_memory_removes_it_and_keeps_the_rest_and_the_consent():
    c, _ = make()
    first = save_note(c, "Lunch with Alex near the office")
    second = save_note(c, "Bought a blue notebook at the corner shop")
    r = c.post(f"/memories/{first}/delete")
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert receipt["reason"] == "deleted" and receipt["removed"]["sources_blanked"] == 1
    assert status(c, first) == "revoked" and status(c, second) == "active"
    assert conn(c).execute("SELECT text FROM sources WHERE source_id=?", (first,)).fetchone()[0] is None
    grants = c.get("/consent/grants").json()
    assert grants and all(g["revoked_at"] is None for g in grants)            # the day's consent is untouched
    assert receipt["summary"]["probes_total"] >= 6
    assert c.get(f"/receipts/{receipt['receipt_id']}").status_code == 200


def test_the_facts_of_a_deleted_memory_are_gone_from_what_you_can_read():
    c, _ = make()
    sid = save_note(c, "Lunch with Alex near the office")
    before = len(c.get("/graph").json()["nodes"])
    assert c.post(f"/memories/{sid}/delete").status_code == 200
    assert conn(c).execute("SELECT COUNT(*) FROM justifications WHERE source_id=?", (sid,)).fetchone()[0] == 0
    assert len(c.get("/graph").json()["nodes"]) <= before


def test_a_video_is_deleted_whole_not_one_part_at_a_time():
    c, _ = make(ManyObjects())
    d = c.post("/capture/preview", json=video_body(6)).json()
    assert commit(c, d, people=[]).status_code == 200
    ids = [r[0] for r in conn(c).execute("SELECT source_id FROM sources WHERE text LIKE 'Video:%'")]
    assert len(ids) == 4
    r = c.post(f"/memories/{ids[2]}/delete")
    assert r.status_code == 200 and r.json()["removed"]["sources_blanked"] == 4
    assert all(status(c, i) == "revoked" for i in ids)


def test_unknown_or_already_deleted_memories_are_404():
    c, _ = make()
    assert c.post("/memories/src-nope/delete").status_code == 404
    sid = save_note(c, "Lunch with Alex near the office")
    assert c.post(f"/memories/{sid}/delete").status_code == 200
    assert c.post(f"/memories/{sid}/delete").status_code == 404


def test_the_same_words_can_be_added_again_later_after_deleting_them():
    c, _ = make()
    sid = save_note(c, "Lunch with Alex near the office")
    c.post(f"/memories/{sid}/delete")
    again = save_note(c, "Lunch with Alex near the office", day="2026-11-05")     # deleting is not a ban on the words
    assert again != sid and status(c, again) == "active"
