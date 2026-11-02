from typing import Any, Protocol


class LLMClient(Protocol):
    """The only surface the compiler and investigator use to reach a model."""

    mode: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]: ...

    def transcribe(self, audio: bytes) -> list[dict[str, Any]]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LLMUnavailable(RuntimeError):
    """Raised when a request cannot be served (no cached response, no credentials)."""
