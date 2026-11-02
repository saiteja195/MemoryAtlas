"""Capture adapters. `MockDayAdapter` replays the scripted demo day (the primary demo path)."""
from pathlib import Path
from typing import Any, Iterator, Protocol

import yaml

from .models import RawCapture


class CaptureAdapter(Protocol):
    def stream(self) -> Iterator[RawCapture]: ...


class MockDayAdapter:
    def __init__(self, script_path: str | Path):
        self.script: dict[str, Any] = yaml.safe_load(Path(script_path).read_text())
        self.owner: str = self.script.get("owner", "me")
        self.names: dict[str, str] = {p["id"]: p["name"] for p in self.script.get("people", [])}

    def grants(self) -> list[dict[str, str]]:
        return self.script.get("grants", [])

    def events(self) -> list[dict[str, Any]]:
        return self.script["events"]

    def capture(self, ev: dict[str, Any]) -> RawCapture:
        """Build the RawCapture for one script event (without media bytes)."""
        day = str(self.script["day"])
        session = self.script.get("sessions", {}).get(ev["session"], {})
        kind = ev["kind"]
        cap = RawCapture(
            kind=kind, session_id=ev["session"], captured_at=f"{day}T{ev['at']}:00",
            lat=ev.get("lat"), lon=ev.get("lon"), ref=ev.get("id"),
            participants=list(session.get("participants", [])),
            speaker_map=dict(session.get("speaker_map", {})))
        if kind == "frame":
            cap.perception = ev.get("perception")
            cap.place_name = ev.get("place_name")
        elif kind == "audio":
            cap.turns = ev.get("turns")
        elif kind == "calendar":
            cap.text = ev["title"]
            cap.place_name = ev.get("location_name")
            cap.ends_at = f"{day}T{ev['ends']}:00" if ev.get("ends") else None
            cap.attendees = list(ev.get("attendees", []))
        elif kind == "note":
            cap.text = ev.get("text")
        return cap

    def stream(self) -> Iterator[RawCapture]:
        for ev in self.events():
            yield self.capture(ev)
