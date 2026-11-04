import base64
import json
import re
import threading
import time
from typing import Any, Callable

import httpx

from .base import LLMUnavailable

_RETRY_STATUS = {429, 500, 502, 503, 504}


class MetaClient:
    """Meta Model API client.

    Verified from the docs: POST /v1/responses with `input_text` content parts, Bearer auth,
    and POST /v1/asr/transcribe (multipart `request` + `audio` WAV parts, DIARIZATION mode).
    Confirmed against the live API on 2026-11-02 with `scripts/smoke_meta.py`: the `system`-role
    message in `input`, the `input_image` content part with a base64 data URL, and diarized
    transcription. NOT yet tried: native structured-output parameters. `complete_json` therefore
    asks for JSON in the prompt and parses it; callers validate with Pydantic.
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
        self._local = threading.local()   # per-thread: the client is shared by overlapping requests

    # -- transport ---------------------------------------------------------------------------

    def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.api_key:
            raise LLMUnavailable("no API key set (MODEL_API_KEY)")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(self._attempts):
            try:
                resp = self._http.post(self.base_url + path, headers=headers, **kwargs)
            except httpx.TransportError as e:       # resets, timeouts, DNS: transient
                if attempt < self._attempts - 1:
                    self._sleep(2 ** attempt)
                    continue
                raise LLMUnavailable(f"{path}: network error {type(e).__name__}") from None
            if resp.status_code in _RETRY_STATUS and attempt < self._attempts - 1:
                self._sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise LLMUnavailable(f"{path} returned {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise LLMUnavailable(f"{path}: retries exhausted")

    @property
    def last_usage(self) -> dict[str, int] | None:
        """Token counts the API reported for this thread's latest call, or None."""
        return getattr(self._local, "usage", None)

    @last_usage.setter
    def last_usage(self, value: dict[str, int] | None) -> None:
        self._local.usage = value

    @staticmethod
    def _read_usage(data: Any) -> dict[str, int] | None:
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            return None
        tin, tout = usage.get("input_tokens"), usage.get("output_tokens")
        if isinstance(tin, bool) or isinstance(tout, bool):
            return None
        if isinstance(tin, int) and isinstance(tout, int):
            return {"tokens_in": tin, "tokens_out": tout}
        return None

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
        self.last_usage = None
        data = self._post("/v1/responses", json=body)
        self.last_usage = self._read_usage(data)
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
            # The model sometimes puts a sentence before the object ("I'll search... {...}").
            # Take the first object that decodes; anything else is still an error.
            value, dec = None, json.JSONDecoder()
            for m in re.finditer(r"\{", text):
                try:
                    cand, _ = dec.raw_decode(text[m.start():])
                except json.JSONDecodeError:
                    continue
                if isinstance(cand, dict):
                    value = cand
                    break
            if value is None:
                raise LLMUnavailable(
                    f"model did not return valid JSON: {e}; got {text[:200]!r}") from e
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
        self.last_usage = None
        data = self._post("/v1/asr/transcribe", files={
            "request": (None, json.dumps(request), "application/json"),
            "audio": ("audio.wav", audio, "audio/wav"),
        })
        self.last_usage = self._read_usage(data)
        turns = [{"turn_id": t["turnId"], "start_ms": t["startMs"], "end_ms": t["endMs"],
                  "speaker": t.get("speaker"), "text": t["transcript"]}
                 for t in data.get("turns", [])]
        if not turns and data.get("transcript"):
            turns = [{"turn_id": 1, "start_ms": 0, "end_ms": data.get("audioDurationMs", 0),
                      "speaker": None, "text": data["transcript"]}]
        return turns
