"""同じcontrollerを通す4場面。期待winnerは含めない。"""
from .engine import Engine
from .evaluation import FixtureEvaluator
import json
from pathlib import Path

CASES = Path(__file__).resolve().parents[2] / "fixtures/conversation_ecology/cases.json"


def run_demo(name, session_id):
    if name not in {"short", "correction", "unsuitable", "work"}: raise ValueError("unknown_demo")
    engine = Engine(FixtureEvaluator(), session_id=session_id)
    case = next(c for c in json.loads(CASES.read_text(encoding="utf8"))["cases"] if c["id"] == name)
    text = case["text"]
    first = engine.ingest(text, phase="partial" if name == "correction" else "finalized")
    if name == "correction":
        engine.advance(30)
        current = engine.ingest(case["revision_text"], revision=True)
        engine.advance(25)
        old = engine.evaluate(first.snapshot_id)
        engine.decide(old["id"])
        engine.advance(300)
        evaluation = engine.evaluate(current.snapshot_id)
    else:
        engine.advance(25)
        evaluation = engine.evaluate(profile="low" if name == "unsuitable" else "balanced")
    engine.decide(evaluation["id"])
    return engine
