"""Deterministic stand-in for the model, so unit tests run offline."""
import json
from typing import Any


def claim(subject, predicate, obj=None, *, subject_type="person", object_type=None, value=None,
          confidence=0.9, text=None, event_time=None):
    return {"subject": subject, "subject_type": subject_type, "predicate": predicate,
            "object": obj, "object_type": object_type, "value": value, "event_time": event_time,
            "confidence": confidence,
            "text": text or f"{subject} {predicate} {obj or value}"}


# What a good model returns for each observation in the demo day (matched by substring).
DEMO_RULES: list[tuple[str, list[dict]]] = [
    ("Blue Door", [
        claim("wallet", "located_at", "Blue Door Café", subject_type="object", object_type="place",
              text="The wallet was at Blue Door Café"),
        claim("Me", "observed_at", "Blue Door Café", object_type="place",
              text="Me was at Blue Door Café")]),
    ("Orbit Fitness", [
        claim("billboard", "has_attribute", subject_type="object", value="advertises: Orbit Fitness",
              text="A billboard advertises Orbit Fitness, first month free")]),
    ("Sync with Alex", [
        claim("Me", "met_with", "Alex", object_type="person", text="Me met with Alex"),
        claim("Me", "attended", "Sync with Alex", object_type="org",
              text="Me attended Sync with Alex"),
        claim("Me", "observed_at", "Office", object_type="place", text="Me was at the Office")]),
    ("taco place", [
        claim("Me", "met_with", "Alex", object_type="person", text="Me met with Alex"),
        claim("taco place", "across_from", "Office", subject_type="place", object_type="place",
              text="The taco place is across the street from the Office"),
        claim("taco place", "has_attribute", subject_type="place", value="awning: green",
              text="The taco place has a green awning"),
        claim("Alex", "said", value="try the taco place across the street from the office with "
              "the green awning, best al pastor",
              text="Alex said to try the taco place across the street from the office, the one "
                   "with the green awning")]),
    ("proposal by Friday", [
        claim("Alex", "committed_to", value="send the proposal by Friday",
              text="Alex committed to send the proposal by Friday")]),
    ("Luna Taqueria", [
        claim("Luna Taqueria", "has_attribute", subject_type="place", value="awning: green",
              text="Luna Taqueria has a green awning"),
        claim("Me", "observed_at", "Luna Taqueria", object_type="place",
              text="Me was at Luna Taqueria")]),
    ("cup holder", [
        claim("wallet", "located_at", "Car", subject_type="object", object_type="place",
              text="The wallet was in the car")]),
]


class FakeLLM:
    mode = "live"

    def __init__(self, rules=None, adjudicate: str | None = None):
        self.rules = DEMO_RULES if rules is None else rules
        self.adjudicate = adjudicate
        self.recall_replies: list[dict] = []   # scripted investigator steps, in order
        self.recall_payloads: list[dict] = []
        self.bind = True                       # False: the model declines every binding
        self.bind_requests: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.transcribed: list[bytes] = []
        self.described: list[bytes] = []
        self.extraction_replies: list[Any] | None = None   # force replies, in order
        self.todo_replies: list[Any] = []      # scripted to-do scan replies (an exception is raised)

    def complete_json(self, system, user, schema):
        self.calls.append((system, user))
        if system.startswith("You answer questions"):
            self.recall_payloads.append(json.loads(user.split("\n\nYour previous")[0]))
            return self.recall_replies.pop(0)
        if system.startswith("You decide whether"):
            return {"match": self.adjudicate}
        if system.startswith("A spoken conversation described a place"):
            self.bind_requests.append(json.loads(user))
            cands = json.loads(user)["candidates"]
            return {"match": cands[0]["id"] if cands and self.bind else None}
        if system.startswith("Write one factual paragraph"):
            return {"summary": f"Summary of {user.count(chr(10)) + 1} claims: "
                            + user.replace("\n", " ")[:120]}
        if system.startswith("You find promises and requests"):
            reply = self.todo_replies.pop(0) if self.todo_replies else {"claims": []}
            if isinstance(reply, Exception):
                raise reply
            return reply
        if self.extraction_replies is not None:
            return self.extraction_replies.pop(0)
        text = json.loads(user.split("\n\nYour previous")[0])["observation"]["text"]
        for key, claims in self.rules:
            if key in text:
                return {"claims": claims}
        return {"claims": []}

    def describe_image(self, image, prompt):
        self.described.append(image)
        return {"caption": "A wallet on a table", "ocr_text": ["Blue Door Café"],
                "objects": [{"label": "wallet", "attrs": {"color": "brown"}}], "scene": "café"}

    def transcribe(self, audio, keywords=None):
        self.transcribed.append(audio)
        self.keywords = keywords
        return [{"turn_id": 1, "start_ms": 0, "end_ms": 2000, "speaker": "B",
                 "text": "You have to try the taco place across the street."}]
