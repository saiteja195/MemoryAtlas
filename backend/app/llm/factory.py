from ..config import Settings, runtime_cache_path
from .base import LLMClient
from .meta import MetaClient
from .replay import RecordReplayClient


def build_client(s: Settings) -> LLMClient:
    meta = MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model)
    if s.llm_mode == "live":
        return meta
    return RecordReplayClient(runtime_cache_path(s), s.llm_mode, inner=meta, seed_dir=s.cache_dir)
