"""Wires the gateway and the compiler together: capture in, graph out."""
import sqlite3
from dataclasses import dataclass

from .capture.gateway import Gateway
from .capture.models import IngestResult, RawCapture
from .compiler.pipeline import CompileResult, Compiler
from .llm.base import LLMClient


@dataclass
class Ingested:
    ingest: IngestResult
    compiled: CompileResult | None = None


class MemoryEngine:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, owner: str = "me",
                 names: dict[str, str] | None = None):
        self.conn, self.llm = conn, llm
        self.gateway = Gateway(conn, llm, owner, names)
        self.compiler = Compiler(conn, llm, owner)

    def ingest(self, cap: RawCapture) -> list[Ingested]:
        out = []
        for res in self.gateway.ingest(cap):
            compiled = self.compiler.compile(res.observation) if res.observation else None
            out.append(Ingested(res, compiled))
        return out
