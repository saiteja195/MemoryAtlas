"""The signed-in owner can withdraw their own consent without a code. Anyone else's consent still needs that
person's code, because the code is what proves it is them."""
from app.privacy.consent import create_grant

from .test_upload_api import commit, make


def saved_note(c):
    d = c.post("/capture/preview", json={"kind": "note", "text": "Lunch with Alex near the office",
                                         "file_modified_at": "2026-11-04T12:00:00"}).json()
    r = commit(c, d)
    assert r.status_code == 200, r.text
    return r.json()["grants"][0]["grant_id"]


def grant(c, gid):
    return next(g for g in c.get("/consent/grants").json() if g["grant_id"] == gid)


def test_the_owner_withdraws_their_own_upload_without_a_code():
    c, _ = make()
    gid = saved_note(c)
    assert grant(c, gid)["revoked_at"] is None
    r = c.post(f"/consent/grants/{gid}/withdraw")
    assert r.status_code == 200, r.text
    assert r.json()["receipt_id"]
    after = grant(c, gid)
    assert after["revoked_at"] is not None and after["ended_reason"] == "withdrawn"


def test_withdrawing_twice_changes_nothing_the_second_time():
    c, _ = make()
    gid = saved_note(c)
    first = c.post(f"/consent/grants/{gid}/withdraw").json()
    second = c.post(f"/consent/grants/{gid}/withdraw")
    assert second.status_code == 200 and second.json()["receipt_id"] == first["receipt_id"]


def test_someone_elses_consent_cannot_be_withdrawn_this_way():
    c, _ = make()
    gid, _token = create_grant(c.app.state.conn, "any-secret", "alex", "upload-2026-11-04")
    c.app.state.conn.commit()
    r = c.post(f"/consent/grants/{gid}/withdraw")
    assert r.status_code == 403 and "code" in r.json()["detail"]
    assert grant(c, gid)["revoked_at"] is None


def test_an_unknown_grant_is_404():
    c, _ = make()
    assert c.post("/consent/grants/grant-nope/withdraw").status_code == 404
