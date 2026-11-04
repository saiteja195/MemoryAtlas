import json

import httpx
import pytest

from app.embed import cosine, embed
from app.llm.base import LLMUnavailable
from app.llm.meta import MetaClient


def client(handler, **kw):
    return MetaClient("https://api.meta.ai", "sk-secret", "muse-spark-1.3",
                      http=httpx.Client(transport=httpx.MockTransport(handler)),
                      sleep=lambda s: None, **kw)


def responses_body(text):
    return {"output": [{"type": "message",
                        "content": [{"type": "output_text", "text": text}]}]}


def test_complete_json_request_shape_and_fence_stripping():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json=responses_body('```json\n{"claims": []}\n```'))

    out = client(handler).complete_json("sys", "user text", {"type": "object"})
    assert out == {"claims": []}
    assert seen["url"] == "https://api.meta.ai/v1/responses"
    assert seen["auth"] == "Bearer sk-secret"
    assert seen["body"]["model"] == "muse-spark-1.3" and seen["body"]["stream"] is False
    assert seen["body"]["input"][1]["content"] == [{"type": "input_text", "text": "user text"}]


def test_json_after_leading_prose_is_accepted():
    text = 'I\'ll look that up. {"action": "tool", "args": {"q": "a {b} c"}} Done.'
    c = client(lambda r: httpx.Response(200, json=responses_body(text)))
    assert c.complete_json("s", "u", {}) == {"action": "tool", "args": {"q": "a {b} c"}}


def test_prose_with_braces_but_no_object_still_raises():
    c = client(lambda r: httpx.Response(200, json=responses_body("use {curly} braces")))
    with pytest.raises(LLMUnavailable):
        c.complete_json("s", "u", {})


def test_invalid_json_raises_unavailable():
    c = client(lambda r: httpx.Response(200, json=responses_body("not json")))
    with pytest.raises(LLMUnavailable):
        c.complete_json("s", "u", {})


def test_describe_image_sends_data_url():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=responses_body('{"caption": "wallet"}'))

    out = client(handler).describe_image(b"\x89PNG\r\n\x1a\nxx", "describe")
    part = seen["body"]["input"][1]["content"][1]
    assert out == {"caption": "wallet"}
    assert part["type"] == "input_image" and part["image_url"].startswith("data:image/png;base64,")


def test_transcribe_multipart_and_turns():
    seen = {}

    def handler(req):
        seen["ctype"], seen["raw"] = req.headers["content-type"], req.content
        seen["url"] = str(req.url)
        return httpx.Response(200, json={
            "transcript": "a b", "audioDurationMs": 5000,
            "turns": [{"turnId": 1, "startMs": 0, "endMs": 2000, "transcript": "Try the taco place.", "speaker": "A"},
                      {"turnId": 2, "startMs": 2500, "endMs": 5000, "transcript": "Will do.", "speaker": "B"}]})

    turns = client(handler).transcribe(b"RIFFwav", keywords=["Alex"])
    assert seen["url"] == "https://api.meta.ai/v1/asr/transcribe"
    assert seen["ctype"].startswith("multipart/form-data")
    assert b'"mode": "DIARIZATION"' in seen["raw"] and b'"keywords": ["Alex"]' in seen["raw"]
    assert b"muse-voice-transcribe-1.0" in seen["raw"] and b"RIFFwav" in seen["raw"]
    assert turns[0] == {"turn_id": 1, "start_ms": 0, "end_ms": 2000, "speaker": "A",
                        "text": "Try the taco place."}
    assert len(turns) == 2


def test_retries_429_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json=responses_body("{}"))

    assert client(handler).complete_json("s", "u", {}) == {}
    assert len(calls) == 3


def test_error_does_not_leak_api_key():
    c = client(lambda r: httpx.Response(401, text="unauthorized"))
    with pytest.raises(LLMUnavailable) as e:
        c.complete_json("s", "u", {})
    assert "sk-secret" not in str(e.value) and "401" in str(e.value)


def test_missing_key_fails_before_any_request():
    c = MetaClient("", "", "", http=httpx.Client(transport=httpx.MockTransport(
        lambda r: pytest.fail("request should not be sent"))))
    with pytest.raises(LLMUnavailable):
        c.complete_json("s", "u", {})


def test_local_embedding_ranks_similar_text_higher():
    q = embed("which restaurant did Alex recommend")
    assert cosine(q, embed("Alex recommended Luna Taqueria")) > cosine(q, embed("orbit fitness billboard"))


def test_transient_network_errors_are_retried_then_surface_as_unavailable():
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ReadError("Connection reset by peer", request=req)
        return httpx.Response(200, json=responses_body('{"ok": true}'))

    assert client(flaky).complete_json("s", "u", {}) == {"ok": True}
    assert calls["n"] == 3

    def down(req):
        raise httpx.ConnectError("sk-secret refused", request=req)

    with pytest.raises(LLMUnavailable) as e:
        client(down).complete_json("s", "u", {})
    assert "ConnectError" in str(e.value) and "sk-secret" not in str(e.value)


def test_meta_client_reads_usage_when_present():
    body = responses_body('{"ok": true}')
    body["usage"] = {"input_tokens": 12, "output_tokens": 7}
    c = client(lambda r: httpx.Response(200, json=body))
    assert c.last_usage is None
    c.complete_json("s", "u", {})
    assert c.last_usage == {"tokens_in": 12, "tokens_out": 7}
    c2 = client(lambda r: httpx.Response(200, json=responses_body('{"ok": true}')))
    c2.complete_json("s", "u", {})
    assert c2.last_usage is None


def test_meta_client_usage_is_reset_and_tolerates_junk():
    state = {"body": {**responses_body("{}"), "usage": {"input_tokens": 3, "output_tokens": 1}}}
    c = client(lambda r: httpx.Response(200, json=state["body"]))
    c.complete_json("s", "u", {})
    assert c.last_usage == {"tokens_in": 3, "tokens_out": 1}
    state["body"] = {**responses_body("{}"), "usage": "weird"}
    c.complete_json("s", "u", {})
    assert c.last_usage is None
