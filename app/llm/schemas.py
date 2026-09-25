"""Output contracts. The JSON schemas are sent as `output_config.format`; the
Pydantic models validate what comes back (never trusted blindly)."""

from pydantic import BaseModel, ConfigDict


class Cited(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    cites: list[str]


class ReleaseSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: Cited
    claims: list[Cited]
    hypotheses: list[Cited]
    caveats: list[Cited]


class ReproNarrativeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: Cited
    steps_prose: list[Cited]
    conditions: list[Cited]
    missing_evidence_questions: list[Cited]


_CITED = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "cites"],
    "additionalProperties": False,
}


def _schema(single: str, lists: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {single: _CITED, **{name: {"type": "array", "items": _CITED} for name in lists}},
        "required": [single, *lists],
        "additionalProperties": False,
    }


RELEASE_SUMMARY_SCHEMA = _schema("headline", ["claims", "hypotheses", "caveats"])
REPRO_NARRATIVE_SCHEMA = _schema("summary", ["steps_prose", "conditions", "missing_evidence_questions"])
