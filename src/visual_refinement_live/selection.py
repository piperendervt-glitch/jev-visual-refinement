"""Q-only provisional selection over one frame and one ComparisonContext."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

THRESHOLD = Decimal("3")


@dataclass(frozen=True)
class SelectionState:
    frame_id: str
    evidence_version: int = 0
    winner_id: str | None = None
    winner_q: str | None = None
    stale_fallback_id: str | None = None


@dataclass(frozen=True)
class Decision:
    candidate_id: str
    evidence_version: int
    previous_winner_id: str | None
    winner_after_id: str | None
    candidate_q: str | None
    previous_winner_q: str | None
    delta_to_previous: str | None
    reason_code: str
    revision_kind: str | None


def update_evidence(state: SelectionState, version: int) -> SelectionState:
    if version != state.evidence_version + 1:
        raise ValueError("evidence_version_not_next")
    return replace(state, evidence_version=version, winner_id=None, winner_q=None,
                   stale_fallback_id=state.winner_id or state.stale_fallback_id)


def decide(state: SelectionState, *, candidate_id: str, evidence_version: int,
           q_status: str, q_decimal: str | None, available: bool) -> tuple[SelectionState, Decision]:
    previous = state.winner_id
    previous_q = state.winner_q
    delta = None
    revision = None
    new = state
    if evidence_version != state.evidence_version:
        reason = "OLD_EVIDENCE"
    elif not available:
        reason = "ARTIFACT_UNAVAILABLE"
    elif q_status != "VALID" or q_decimal is None:
        reason = "Q_UNAVAILABLE"
    else:
        q = Decimal(q_decimal)
        if not q.is_finite() or not Decimal(0) <= q <= Decimal(4):
            raise ValueError("q_invalid")
        if q < THRESHOLD:
            reason = "BELOW_Q_THRESHOLD"
        elif previous is None:
            reason = ("REFRESHED_SAME_CANDIDATE" if candidate_id == state.stale_fallback_id
                      else "FIRST_ELIGIBLE" if evidence_version == 0
                      else "FIRST_ELIGIBLE_IN_NEW_EVIDENCE")
            revision = "REFRESH_SAME" if candidate_id == state.stale_fallback_id else "SELECT"
            new = replace(state, winner_id=candidate_id, winner_q=q_decimal,
                          stale_fallback_id=None)
        else:
            delta = format(q - Decimal(previous_q), "f")
            if q > Decimal(previous_q):
                reason = "HIGHER_Q"
                revision = "REFRESH_SAME" if candidate_id == previous else "REPLACE"
                new = replace(state, winner_id=candidate_id, winner_q=q_decimal,
                              stale_fallback_id=None)
            elif q == Decimal(previous_q):
                reason = "TIE_KEEP_CURRENT"
            else:
                reason = "LOWER_Q"
    decision = Decision(candidate_id, evidence_version, previous, new.winner_id,
                        q_decimal if q_status == "VALID" else None,
                        previous_q, delta, reason, revision)
    return new, decision
