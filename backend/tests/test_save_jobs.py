"""Saving a memory runs in the background: the request returns at once and the page polls for the result, so a
slow model can never time out the request, and the page can show that Muse is still working."""
import threading
import time

import pytest

from app import api as api_module
from app.llm.base import LLMUnavailable

from .fakes import FakeLLM
from .test_upload_api import make, preview_photo
from .test_profiles_api import make_app, new_client, signup


def start(c, draft, **answers):
    return c.post("/capture/commit/start", json={"draft_id": draft["draft_id"], "answers": answers})


def wait_for(c, job_id, state="done", timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        body = c.get(f"/capture/commit/jobs/{job_id}").json()
        if body["state"] == state:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job never reached {state}: {body}")


class GatedLLM(FakeLLM):
    """A model that waits for the test before it answers, like a slow one."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def complete_json(self, system, user, schema):
        self.entered.set()
        assert self.release.wait(10), "the test never released the model"
        return super().complete_json(system, user, schema)


def test_the_save_finishes_in_the_background_with_the_same_result_as_before():
    c, _ = make()
    r = start(c, preview_photo(c))
    assert r.status_code == 202 and r.json()["job_id"]
    done = wait_for(c, r.json()["job_id"])
    assert done["result"]["session_id"] == "upload-2026-10-29"
    assert c.app.state.conn.execute("SELECT COUNT(*) FROM sources WHERE session_id LIKE 'upload-%'").fetchone()[0] >= 1
    assert done["error"] is None and done["calls_done"] >= 1


def test_a_slow_model_does_not_hold_the_request_and_progress_is_reported():
    llm = GatedLLM()
    c, _ = make(llm)
    t0 = time.time()
    job_id = start(c, preview_photo(c)).json()["job_id"]
    assert time.time() - t0 < 5                       # returned while the model is still "thinking"
    assert llm.entered.wait(5)
    running = c.get(f"/capture/commit/jobs/{job_id}").json()
    assert running["state"] == "running" and running["result"] is None
    assert running["calls_started"] >= 1 and running["calls_done"] < running["calls_started"]
    assert running["elapsed_s"] >= 0 and running["working_s"] >= 0
    llm.release.set()
    assert wait_for(c, job_id)["state"] == "done"


def test_only_one_save_runs_at_a_time_per_profile():
    llm = GatedLLM()
    c, _ = make(llm)
    first = start(c, preview_photo(c)).json()["job_id"]
    assert llm.entered.wait(5)
    second = start(c, preview_photo(c))
    assert second.status_code == 409 and "already being saved" in second.json()["detail"]
    llm.release.set()
    wait_for(c, first)
    assert start(c, preview_photo(c)).status_code == 202      # free again once the first is done


def test_a_failed_save_says_why_and_the_job_is_over(monkeypatch):
    c, _ = make()

    def boom(*a, **k):
        raise LLMUnavailable("the model API is down")

    monkeypatch.setattr(api_module, "commit_draft", boom)
    job_id = start(c, preview_photo(c)).json()["job_id"]
    failed = wait_for(c, job_id, "error")
    assert failed["result"] is None
    assert failed["error"] == {"status": 503, "message": "the model API is down"}


def test_an_unexpected_failure_is_reported_without_leaking_details(monkeypatch):
    c, _ = make()

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(api_module, "commit_draft", boom)
    failed = wait_for(c, start(c, preview_photo(c)).json()["job_id"], "error")
    assert failed["error"]["status"] == 500 and "secret internal detail" not in failed["error"]["message"]


def test_start_checks_the_draft_like_the_plain_commit_does():
    c, _ = make()
    assert c.post("/capture/commit/start", json={"draft_id": "nope", "answers": {}}).status_code == 404
    d = preview_photo(c)
    first = start(c, d)
    assert first.status_code == 202
    wait_for(c, first.json()["job_id"])
    assert start(c, d).status_code == 404                     # the draft was taken by the first call


def test_an_unknown_job_is_404_and_a_job_belongs_to_one_profile(tmp_path):
    app = make_app(tmp_path, FakeLLM())
    a, b = new_client(app), new_client(app)
    signup(a, "Alpha One", "passcode-one")
    signup(b, "Beta Two", "passcode-two")
    assert a.post("/demo/load-sample").status_code == 200
    job_id = start(a, preview_photo(a)).json()["job_id"]
    wait_for(a, job_id)
    assert b.get(f"/capture/commit/jobs/{job_id}").status_code == 404
    assert a.get("/capture/commit/jobs/does-not-exist").status_code == 404
    assert new_client(app).get(f"/capture/commit/jobs/{job_id}").status_code == 401
