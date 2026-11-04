"""Background work: preview and answers run as jobs the page polls, one preview and one answer per profile may run
side by side, and every stored copy of a result is cleared when a memory is forgotten."""
import threading
import time

import pytest

from .fakes import FakeLLM
from .test_delete_memory import save_note
from .test_upload_api import b64, make, png

NOTE = {"kind": "note", "text": "Lunch with Alex near the office", "file_modified_at": "2026-11-04T12:00:00"}
SECRET_TEXT = "Lunch with Alex at the Blue Door"


def wait_done(c, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f"/jobs/{job_id}").json()
        if s["state"] not in ("queued", "running"):
            return s
        time.sleep(0.02)
    raise AssertionError("job never finished")


class Gated(FakeLLM):
    """A model whose photo reading waits until the test lets it go."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.entered = threading.Event()

    def describe_image(self, image, prompt):
        self.entered.set()
        assert self.release.wait(10)
        return super().describe_image(image, prompt)


def photo_body():
    return {"kind": "frame", "data_b64": b64(png()), "file_modified_at": "2026-11-04T12:00:00"}


def put_answer_job(c, text=SECRET_TEXT):
    """A finished answer job that quotes a memory, as the assistant would leave behind."""
    job = c.app.state.jobs.start("local", lambda: {"status": "answered", "answer": text}, kind="answer", lane="answer")
    wait_done(c, job.job_id)
    return job.job_id


# -- the jobs themselves -----------------------------------------------------------------------------

def test_a_preview_returns_at_once_and_the_job_holds_the_draft():
    c, _ = make()
    r = c.post("/capture/preview/start", json=NOTE)
    assert r.status_code == 202
    done = wait_done(c, r.json()["job_id"])
    assert done["state"] == "done" and done["kind"] == "preview" and done["result"]["draft_id"]
    assert [j["job_id"] for j in c.get("/jobs").json()] == [r.json()["job_id"]]
    assert c.delete(f"/jobs/{r.json()['job_id']}").status_code == 204
    assert c.get(f"/jobs/{r.json()['job_id']}").status_code == 404


def test_a_job_that_is_still_running_cannot_be_dismissed():
    fake = Gated()
    c, _ = make(fake)
    jid = c.post("/capture/preview/start", json=photo_body()).json()["job_id"]
    assert fake.entered.wait(5)
    assert c.delete(f"/jobs/{jid}").status_code == 409
    fake.release.set()
    assert wait_done(c, jid)["state"] == "done"


def test_one_preview_at_a_time_but_an_answer_can_run_beside_it():
    fake = Gated()
    c, _ = make(fake)
    first = c.post("/capture/preview/start", json=photo_body()).json()["job_id"]
    assert fake.entered.wait(5)
    assert c.post("/capture/preview/start", json=photo_body()).status_code == 409        # the preview lane is busy
    ask = c.post("/recall/ask/start", json={"question": "Who did I meet?"})
    assert ask.status_code == 202
    wait_done(c, ask.json()["job_id"])                                                      # not held up by the preview
    assert c.get(f"/jobs/{first}").json()["state"] == "running"
    fake.release.set()
    assert wait_done(c, first)["state"] == "done"


def test_the_page_stays_responsive_while_a_job_runs():
    fake = Gated()
    c, _ = make(fake)
    jid = c.post("/capture/preview/start", json=photo_body()).json()["job_id"]
    assert fake.entered.wait(5)
    start = time.time()
    assert c.get("/graph").status_code == 200 and c.get("/jobs").status_code == 200
    assert time.time() - start < 1.0
    fake.release.set()
    wait_done(c, jid)


def test_a_job_belongs_to_one_profile(tmp_path):
    from .test_profiles_api import make_app, new_client, signup
    app = make_app(tmp_path)
    a, b = new_client(app), new_client(app)
    signup(a, "Ann"), signup(b, "Ben")
    app.state.jobs.start(a.get("/auth/me").json()["profile"]["profile_id"], lambda: {"x": 1}, kind="answer", lane="answer")
    assert len(a.get("/jobs").json()) == 1 and b.get("/jobs").json() == []


# -- forgetting clears every stored copy ---------------------------------------------------------------

def grant_id(c):
    return next(g["grant_id"] for g in c.get("/consent/grants").json() if g["scope_ref"].startswith("upload-"))


def forgetters():
    return {
        "delete a memory": lambda c, sid: c.post(f"/memories/{sid}/delete?red_team=false"),
        "withdraw consent": lambda c, sid: c.post(f"/consent/grants/{grant_id(c)}/withdraw?red_team=false"),
        "expire a consent": lambda c, sid: c.post(f"/demo/grants/{grant_id(c)}/expire"),
    }


@pytest.mark.parametrize("how", ["delete a memory", "withdraw consent", "expire a consent"])
def test_forgetting_clears_finished_answers_and_unsaved_drafts(how):
    c, _ = make()
    sid = save_note(c, "Lunch with Alex near the office")
    jid = put_answer_job(c)
    draft = c.post("/capture/preview", json=NOTE).json()["draft_id"]
    assert c.get(f"/jobs/{jid}").status_code == 200
    r = forgetters()[how](c, sid)
    assert r.status_code == 200, r.text
    assert c.get(f"/jobs/{jid}").status_code == 404
    assert SECRET_TEXT not in c.get("/jobs").text
    assert c.post("/capture/commit/start", json={"draft_id": draft, "answers": {"people": []}}).status_code == 404


def test_a_consent_that_lapses_is_noticed_by_the_next_request():
    c, _ = make()
    save_note(c, "Lunch with Alex near the office")
    jid = put_answer_job(c)
    conn = c.app.state.conn
    conn.execute("UPDATE consent_grants SET expires_at='2000-01-01T00:00:00' WHERE scope_ref LIKE 'upload-%'")
    conn.commit()
    assert c.get("/jobs").status_code == 200                       # any request runs the expiry sweep
    assert c.get(f"/jobs/{jid}").status_code == 404


def test_a_job_that_was_running_when_something_was_forgotten_publishes_nothing():
    fake = Gated()
    c, _ = make(fake)
    sid = save_note(c, "Lunch with Alex near the office")
    jid = c.post("/capture/preview/start", json=photo_body()).json()["job_id"]
    assert fake.entered.wait(5)
    assert c.post(f"/memories/{sid}/delete?red_team=false").status_code == 200
    fake.release.set()
    time.sleep(0.3)
    s = c.get(f"/jobs/{jid}")
    assert s.status_code == 404 or (s.json()["result"] is None)
