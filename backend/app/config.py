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
    cache_dir: str = os.getenv("MEMORYATLAS_CACHE_DIR", str(ROOT / "fixtures" / "llm_cache"))
    demo_script: str = os.getenv("MEMORYATLAS_DEMO_SCRIPT",
                                 str(ROOT / "fixtures" / "demo_day" / "script.yaml"))
    # Keys the HMAC of consent revocation tokens (simulated authenticated action).
    revocation_secret: str = os.getenv("MEMORYATLAS_SECRET", "dev-only-secret")
