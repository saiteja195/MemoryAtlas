import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root, so paths do not depend on the cwd


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("MEMORYATLAS_DB", "memoryatlas.db")
    # live: call the Meta Model API. record: live + cache responses.
    # replay: cached responses only (offline). The UI must show this mode.
    llm_mode: str = os.getenv("MEMORYATLAS_LLM_MODE", "replay")
    llm_base_url: str = os.getenv("META_API_BASE_URL", "https://api.meta.ai")
    llm_api_key: str = os.getenv("MODEL_API_KEY", "")
    llm_model: str = os.getenv("META_MODEL", "muse-spark-1.3")
    asr_model: str = os.getenv("META_ASR_MODEL", "muse-voice-transcribe-1.0")
    cache_dir: str = os.getenv("MEMORYATLAS_CACHE_DIR", str(ROOT / "fixtures" / "llm_cache"))
    demo_script: str = os.getenv("MEMORYATLAS_DEMO_SCRIPT",
                                 str(ROOT / "fixtures" / "demo_day" / "script.yaml"))
    # Where the app writes model responses at run time. The committed `cache_dir` is read-only
    # seed data; a forgetting purge cleans this directory. "" means: next to the database.
    runtime_cache_dir: str = os.getenv("MEMORYATLAS_RUNTIME_CACHE", "")
    # Keys the HMAC of consent revocation tokens (simulated authenticated action).
    revocation_secret: str = os.getenv("MEMORYATLAS_SECRET", "dev-only-secret")
    # Profiles: on means every person signs in and gets a private database; off is the single-user
    # mode used by development and the older tests.
    auth: bool = os.getenv("MEMORYATLAS_AUTH", "on") != "off"
    # Where the profile registry and each profile's database live. "" means: next to `db_path`.
    data_dir: str = os.getenv("MEMORYATLAS_DATA_DIR", "")


def runtime_cache_path(s: Settings) -> str:
    """The directory the running app records model responses into."""
    if s.runtime_cache_dir:
        return s.runtime_cache_dir
    if s.db_path == ":memory:":
        import tempfile
        return tempfile.mkdtemp(prefix="memoryatlas-llm-")
    return str(Path(s.db_path).resolve()) + ".llmcache"
