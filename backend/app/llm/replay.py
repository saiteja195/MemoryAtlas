import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .base import LLMClient, LLMUnavailable


ERROR_KEY = "__llm_error__"
CONTENT_ERRORS = ("did not return valid JSON", "JSON that is not an object")


class RecordReplayClient:
    """Caches every model call by request hash.

    record: delegate to `inner`, then store the response.
    replay: serve from disk only; a miss raises LLMUnavailable, never a guess.
    """

    def __init__(self, cache_dir: str, mode: str, inner: LLMClient | None = None,
                 seed_dir: str | None = None):
        if mode not in ("record", "replay"):
            raise ValueError(f"mode must be record or replay, got {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs an inner client")
        self.mode = mode
        self._dir = Path(cache_dir)
        # Read-only recorded fixtures (the committed demo day). Lookups fall back to it, but
        # nothing is ever written to or deleted from it, so a purge of `cache_dir` is complete.
        self._seed = Path(seed_dir) if seed_dir else None
        self._inner = inner
        # Per-thread: the client is shared by overlapping requests, and each caller must read
        # the label of its own call.
        self._local = threading.local()
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def last_served(self) -> str:
        """Where this thread's latest call was answered from: "cache" (a recorded response, or
        a miss in replay mode, which never reaches the model) or "live"."""
        return getattr(self._local, "served", "live")

    @staticmethod
    def _key(method: str, payload: dict[str, Any]) -> str:
        blob = json.dumps({"m": method, "p": payload}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _call(self, method: str, payload: dict[str, Any], *args: Any) -> Any:
        name = f"{self._key(method, payload)}.json"
        path = self._dir / name
        for candidate in (path, self._seed / name if self._seed else None):
            if candidate is not None and candidate.exists():
                data = json.loads(candidate.read_text())
                self._local.served = "cache"
                if isinstance(data, dict) and ERROR_KEY in data:
                    raise LLMUnavailable(data[ERROR_KEY])  # the model's unusable reply, replayed
                return data
        if self.mode == "replay":
            self._local.served = "cache"      # a miss never reaches the model
            raise LLMUnavailable(f"no recorded response for {method} ({path.name})")
        self._local.served = "live"
        try:
            result = getattr(self._inner, method)(*args)
        except LLMUnavailable as e:
            # An unparseable model reply is deterministic content, not an outage: record it so a
            # replay takes the same retry path. Network and HTTP errors are never recorded.
            if any(m in str(e) for m in CONTENT_ERRORS):
                path.write_text(json.dumps({ERROR_KEY: str(e)}, indent=2))
            raise
        path.write_text(json.dumps(result, indent=2, sort_keys=True))
        # Hand back exactly what replay will: key order differences would change later request
        # hashes (callers serialise results into the next prompt) and break offline replay.
        return json.loads(path.read_text())

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        return self._call("complete_json", {"s": system, "u": user, "schema": schema},
                          system, user, schema)

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]:
        digest = hashlib.sha256(image).hexdigest()
        return self._call("describe_image", {"img": digest, "p": prompt}, image, prompt)

    def transcribe(self, audio: bytes, keywords: list[str] | None = None) -> list[dict[str, Any]]:
        payload = {"a": hashlib.sha256(audio).hexdigest(), "k": keywords}
        return self._call("transcribe", payload, audio, keywords)
