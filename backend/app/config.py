import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("MEMORYATLAS_DB", "memoryatlas.db")
    # live: call the Meta Model API. record: live + cache responses.
    # replay: cached responses only (offline). The UI must show this mode.
    llm_mode: str = os.getenv("MEMORYATLAS_LLM_MODE", "replay")
    llm_base_url: str = os.getenv("META_API_BASE_URL", "")
    llm_api_key: str = os.getenv("META_API_KEY", "")
    llm_model: str = os.getenv("META_MODEL", "")
    cache_dir: str = os.getenv("MEMORYATLAS_CACHE_DIR", "fixtures/llm_cache")
