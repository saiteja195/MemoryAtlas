import base64
import json
import re
import time
from typing import Any, Callable

import httpx

from .base import LLMUnavailable

_RETRY_STATUS = {429, 500, 502, 503, 504}


class MetaClient:
    """Meta Model API client.

    Verified from the docs: POST /v1/responses with `input_text` content parts, Bearer auth,
    and POST /v1/asr/transcribe (multipart `request` + `audio` WAV parts, DIARIZATION mode).
    NOT yet verified against the live API: the system-message shape, the `input_image` content
    part, and structured-output parameters. `complete_json` therefore asks for JSON in the
    prompt and parses it; callers validate with Pydantic. Run `scripts/smoke_meta.py` with a
    key to confirm each shape.
    """

    mode = "live"

    def __init__(self, base_url: str, api_key: str, model: str,
                 asr_model: str = "muse-voice-transcribe-1.0",
                 http: httpx.Client | None = None, attempts: int = 3,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = (base_url or "https://api.meta.ai").rstrip("/")
        self.api_key, self.model, self.asr_model = api_key, model or "muse-spark-1.3", asr_model
        self._http = http or httpx.Client(timeout=120)
        self._attempts, self._sleep = attempts, sleep

    # -- transport ---------------------------------------------------------------------------

    def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.api_key:
            raise LLMUnavailable("no API key set (MODEL_API_KEY)")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(self._attempts):
            resp = self._http.post(self.base_url + path, headers=headers, **kwargs)
            if resp.status_code in _RETRY_STATUS and attempt < self._attempts - 1:
                self._sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise LLMUnavailable(f"{path} returned {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise LLMUnavailable(f"{path}: retries exhausted")

    # -- text and vision ---------------------------------------------------------------------

    def _responses_text(self, system: str, parts: list[dict[str, Any]]) -> str:
        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": parts},
            ],
            "stream": False,
        }
        data = self._post("/v1/responses", json=body)
        chunks = [c.get("text", "")
                  for item in data.get("output", []) if item.get("type") == "message"
                  for c in item.get("content", []) if c.get("type") == "output_text"]
        text = "".join(chunks) or data.get("output_text") or ""
        if not text:
            raise LLMUnavailable(f"/v1/responses had no text output: {str(data)[:300]}")
        return text

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            value = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMUnavailable(f"model did not return valid JSON: {e}; got {text[:200]!r}") from e
        if not isinstance(value, dict):
            raise LLMUnavailable("model returned JSON that is not an object")
        return value

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        system = (f"{system}\n\nRespond with a single JSON object and nothing else. "
                  f"It must match this JSON Schema:\n{json.dumps(schema)}")
        return self._parse_json(
            self._responses_text(system, [{"type": "input_text", "text": user}]))

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]:
        mime = "image/png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        parts = [{"type": "input_text", "text": prompt},
                 {"type": "input_image", "image_url": url}]
        return self._parse_json(self._responses_text(
            "You describe photos for a memory system. Respond with a single JSON object only.",
            parts))

    # -- speech ------------------------------------------------------------------------------

    def transcribe(self, audio: bytes, keywords: list[str] | None = None) -> list[dict[str, Any]]:
        """`audio` must be mono 16-bit PCM WAV at 16 or 24 kHz, at most 10 minutes."""
        request = {"mode": "DIARIZATION", "model": self.asr_model, "audioEncoding": "WAV",
                   "languageBias": ["English"]}
        if keywords:
            request["keywords"] = keywords
        data = self._post("/v1/asr/transcribe", files={
            "request": (None, json.dumps(request), "application/json"),
            "audio": ("audio.wav", audio, "audio/wav"),
        })
        turns = [{"turn_id": t["turnId"], "start_ms": t["startMs"], "end_ms": t["endMs"],
                  "speaker": t.get("speaker"), "text": t["transcript"]}
                 for t in data.get("turns", [])]
        if not turns and data.get("transcript"):
            turns = [{"turn_id": 1, "start_ms": 0, "end_ms": data.get("audioDurationMs", 0),
                      "speaker": None, "text": data["transcript"]}]
        return turns
