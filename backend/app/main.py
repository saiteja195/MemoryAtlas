from fastapi import FastAPI

from . import db
from .config import Settings
from .llm.factory import build_client

settings = Settings()
conn = db.connect(settings.db_path)
llm = build_client(settings)

app = FastAPI(title="MemoryAtlas")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_mode": llm.mode}
