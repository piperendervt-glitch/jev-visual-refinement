"""不変snapshotと、fixtureで使う明示的な時計。単位はミリ秒。"""
from dataclasses import asdict, dataclass
import math

DEADLINE_MS = 750
EVALUATION_INTERVAL_MS = 300
COLLECTION_MS = 25
BACKCHANNEL_COOLDOWN_MS = 1500
THRESHOLD = .65


def number(value, low=0, high=1_000_000):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("invalid_number")
    return value


class FixtureClock:
    def __init__(self):
        self.now_ms = 0

    def advance(self, milliseconds):
        self.now_ms += number(milliseconds, high=60_000)


@dataclass(frozen=True)
class TurnSnapshot:
    session_id: str
    subject_scope: str
    turn_id: str
    utterance_revision: int
    decision_cycle_id: str
    snapshot_id: str
    context_snapshot_id: str
    source_cutoff: int
    available_cursor: int
    created_ms: float
    deadline_ms: float
    text: str
    phase: str
    source: str
    history_refs: tuple = ()
    explicit_constraints: tuple = ("fixture_only", "no_authority")
    work_states: tuple = ()
    backend_registry_version: str = "c0-disconnected-v1"
    mode: str = "FIXTURE"

    def data(self):
        # JSON-shaped detached value; callers cannot change the snapshot.
        import json
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True)
class Candidate:
    id: str
    snapshot_id: str
    turn_id: str
    revision: int
    text: str
    act: str
    slot: str
    prerequisites: tuple
    proposers: tuple
    eligible: bool = True

    def data(self):
        import json
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))
