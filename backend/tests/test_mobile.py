import base64
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Settings
from app.mobile import MAX_PHOTO_BYTES, create_mobile_app
from .fakes import FakeLLM

TOKEN = "phone-access-token-for-tests-only-123456"
JPEG = b"\xff\xd8\xff-real-glasses-photo-test\xff\xd9"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def phone(tmp_path):
    settings = Settings(db_path=str(tmp_path / "phone.db"), llm_mode="live")
    fake = FakeLLM()
    app = create_mobile_app(settings, llm=fake, token=TOKEN)
    with TestClient(app) as client:
        yield client, settings, fake


def capture(client, **overrides):
    session = client.post("/mobile/sessions", headers=HEADERS).json()
    return {"session_id": session["session_id"], "captured_at": "2026-11-02T12:34:56Z",
            "image_b64": base64.b64encode(JPEG).decode(), **overrides}


@pytest.mark.parametrize("path,method", [("/mobile/health", "get"), ("/mobile/sessions", "post"),
                                         ("/mobile/photos", "post")])
def test_phone_routes_require_the_token(phone, path, method):
    client, _, fake = phone
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = (client.post(path, headers=headers, json={}) if method == "post"
                    else client.get(path, headers=headers))
        assert response.status_code == 401
    assert not fake.described


def test_gateway_has_no_demo_or_unprotected_graph_routes(phone):
    client, _, _ = phone
    for path in ("/demo/grants", "/graph", "/docs", "/openapi.json", "/export"):
        assert client.get(path, headers=HEADERS).status_code == 404


def test_real_photo_compiles_and_stores_only_text(phone, tmp_path):
    client, settings, fake = phone
    body = capture(client)
    result = client.post("/mobile/photos", headers=HEADERS, json=body)
    assert result.status_code == 200, result.text
    out = result.json()
    assert out["status"] == "stored" and out["claims"] > 0 and out["claim_ids"]
    assert "wallet" in out["observation"] and out["raw_media_bytes_retained"] == 0
    assert fake.described == [JPEG]
    assert "+" not in out["event_time"] and not out["event_time"].endswith("Z")
    conn = db.connect(settings.db_path)
    assert conn.execute("SELECT count(*) FROM sources WHERE media_bytes_retained!=0").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM claims").fetchone()[0] > 0
    conn.close()
    assert not list(tmp_path.rglob("*.jpg"))


def test_revoked_or_foreign_session_is_rejected_before_perception(phone):
    client, settings, fake = phone
    body = capture(client)
    conn = db.connect(settings.db_path)
    conn.execute("UPDATE consent_grants SET revoked_at='now'")
    conn.commit()
    conn.close()
    assert client.post("/mobile/photos", headers=HEADERS, json=body).status_code == 403
    body["session_id"] = "day-1"
    assert client.post("/mobile/photos", headers=HEADERS, json=body).status_code == 403
    assert not fake.described


@pytest.mark.parametrize("image", ["not-base64", base64.b64encode(b"not a jpeg").decode()])
def test_invalid_images_never_reach_model(phone, image):
    client, _, fake = phone
    response = client.post("/mobile/photos", headers=HEADERS, json=capture(client, image_b64=image))
    assert response.status_code == 422 and not fake.described


def test_timestamp_must_include_timezone_and_validation_does_not_echo_photo(phone):
    client, _, fake = phone
    response = client.post("/mobile/photos", headers=HEADERS,
                           json=capture(client, captured_at="2026-11-02T12:34:56"))
    assert response.status_code == 422 and not fake.described
    assert base64.b64encode(JPEG).decode() not in response.text


def test_replay_mode_is_caught_before_phone_sends_photo():
    fake = FakeLLM()
    fake.mode = "replay"
    with TestClient(create_mobile_app(Settings(db_path=":memory:"), fake, TOKEN)) as client:
        assert client.get("/mobile/health", headers=HEADERS).status_code == 409
        assert client.post("/mobile/sessions", headers=HEADERS).status_code == 409
    assert not fake.described


def test_missing_live_key_is_reported_without_credentials():
    with TestClient(create_mobile_app(Settings(db_path=":memory:", llm_mode="live", llm_api_key=""),
                                     token=TOKEN)) as client:
        assert client.get("/mobile/health", headers=HEADERS).status_code == 503


def test_no_false_success_when_photo_produces_no_claims(phone):
    client, _, fake = phone
    fake.rules = []
    result = client.post("/mobile/photos", headers=HEADERS, json=capture(client))
    assert result.status_code == 422 and "no memory" in result.json()["detail"]


def test_token_is_required_at_startup():
    with pytest.raises(RuntimeError, match="MOBILE_TOKEN"):
        create_mobile_app(Settings(db_path=":memory:"), FakeLLM(), token="short")
