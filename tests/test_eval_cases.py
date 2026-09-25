"""The frozen inputs of the reproduction-narrative eval (evals/repro_narrative).

Offline: no model calls. Guards that the synthetic packets are still exactly
what the real pipeline produces (so a builder change can't silently leave the
eval measuring stale inputs) and that no packet carries an identifier."""

import json
import re
from pathlib import Path

import pytest

from evals.repro_narrative.build_cases import CASES_DIR, REAL, SYNTHETIC, build

CASES = {p.stem: json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))}
IDENTIFIER = re.compile(r"install-|account-|\b\d{9,}\b|[0-9a-f]{32}|@")


def test_case_set_is_complete() -> None:
    assert set(CASES) == set(REAL) | {s.id for s in SYNTHETIC}


@pytest.mark.parametrize("synthetic", SYNTHETIC, ids=lambda s: s.id)
def test_synthetic_packet_matches_the_pipeline(synthetic) -> None:
    stored = CASES[synthetic.id]["packet"]
    assert json.loads(json.dumps(build(synthetic), sort_keys=True, default=str)) == stored


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_no_identifiers_in_packets(case_id: str) -> None:
    assert not IDENTIFIER.findall(json.dumps(CASES[case_id]["packet"]))
