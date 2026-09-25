"""Programmatic grader of the reproduction-narrative eval, checked on known-good
and known-bad outputs for every frozen case (offline; the judge is not called)."""

import json

import pytest

from evals.repro_narrative import grade
from evals.repro_narrative.build_cases import CASES_DIR

PACKETS = {p.stem: json.loads(p.read_text())["packet"] for p in sorted(CASES_DIR.glob("*.json"))}


def _oracle(packet: dict) -> dict:
    """Cites every critical item, narrates the steps in order, asks about every gap."""
    ids = [i["id"] for i in packet["items"]]
    return {
        "summary": {"text": "incident", "cites": ["incident"]},
        "steps_prose": [{"text": s, "cites": [s]} for s in ids if s.startswith("step-")],
        "conditions": [{"text": c, "cites": [c]} for c in grade.critical_ids(packet)],
        "missing_evidence_questions": [{"text": g, "cites": [g]} for g in ids if g.startswith("gap-")],
    }


@pytest.mark.parametrize("case", sorted(PACKETS))
def test_oracle_scores_full_marks(case: str) -> None:
    assert grade.programmatic(PACKETS[case], _oracle(PACKETS[case]), []) == {
        "grounded": 1.0, "coverage": 1.0, "steps_in_order": 1.0, "gaps_questioned": 1.0}


def test_null_output_scores_zero_where_something_was_required() -> None:
    scores = grade.programmatic(PACKETS["RP2"], None, [])
    assert scores == {"grounded": 0.0, "coverage": 0.0, "steps_in_order": 0.0, "gaps_questioned": 0.0}


def test_reversed_steps_and_rejected_claims_are_penalized() -> None:
    packet = PACKETS["RP1"]
    output = _oracle(packet)
    output["steps_prose"].reverse()
    rejected = [{"text": "made up", "cites": [], "reason": "NO_CITATION"}] * len(grade.entries(output))
    scores = grade.programmatic(packet, output, rejected)
    assert scores["steps_in_order"] == 0.0 and scores["grounded"] == 0.5
