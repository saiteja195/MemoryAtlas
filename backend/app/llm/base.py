from typing import Any, Protocol


class LLMClient(Protocol):
    """The only surface the compiler and investigator use to reach a model."""

    mode: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]: ...

    def transcribe(self, audio: bytes, keywords: list[str] | None = None) -> list[dict[str, Any]]:
        """Diarized turns: [{turn_id, start_ms, end_ms, speaker, text}]."""
        ...


class LLMUnavailable(RuntimeError):
    """Raised when a request cannot be served (no cached response, no credentials, API error)."""
