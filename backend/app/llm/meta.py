from typing import Any

from .base import LLMUnavailable


class MetaClient:
    """Meta Model API client.

    Endpoint paths, model ids and request shapes are NOT wired yet: they must
    come from the Meta docs (see docs/HACKATHON_FACTS.md, Day-0 checks #3-4).
    Until then every call raises LLMUnavailable instead of guessing.
    """

    mode = "live"

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url, api_key, model

    def _not_wired(self, what: str) -> LLMUnavailable:
        return LLMUnavailable(
            f"MetaClient.{what} is not wired; verify the API in docs/HACKATHON_FACTS.md first")

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        raise self._not_wired("complete_json")

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]:
        raise self._not_wired("describe_image")

    def transcribe(self, audio: bytes) -> list[dict[str, Any]]:
        raise self._not_wired("transcribe")

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise self._not_wired("embed")
