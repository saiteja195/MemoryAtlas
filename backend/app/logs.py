"""Server logging for the app's own loggers ("memoryatlas" and "memoryatlas.llm"): one line per model call and a
warning for a slow or retried one. Without this only warnings reach the container log."""
import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    log = logging.getLogger("memoryatlas")
    log.setLevel(logging.INFO)
    if not any(getattr(h, "_memoryatlas", False) for h in log.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._memoryatlas = True          # type: ignore[attr-defined]  marks ours, so a second call adds nothing
        log.addHandler(handler)
