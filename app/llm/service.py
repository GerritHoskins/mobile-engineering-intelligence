"""Explain a deterministic result in prose: stored per exact input, validated
against the output schema, and citation-checked against the evidence packet."""

from functools import lru_cache

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.llm import config, prompts
from app.llm.citations import NothingGrounded, enforce
from app.llm.client import AnthropicLLM, LLMClient, LLMError, LLMMisconfigured
from app.llm.packet import ids, input_hash
from app.llm.schemas import (
    REPRO_NARRATIVE_SCHEMA, RELEASE_SUMMARY_SCHEMA, ReleaseSummaryOut, ReproNarrativeOut,
)
from app.models import LlmOutput
from app.orgs import OrgConfig

KINDS = {
    "release_summary": (prompts.RELEASE_TASK, RELEASE_SUMMARY_SCHEMA, ReleaseSummaryOut),
    "repro_narrative": (prompts.REPRO_TASK, REPRO_NARRATIVE_SCHEMA, ReproNarrativeOut),
}


@lru_cache(maxsize=1)
def default_client() -> LLMClient:
    try:
        return AnthropicLLM()
    except Exception as error:  # the SDK raises at construction when no credentials resolve
        raise LLMMisconfigured(f"Could not create the Anthropic client: {error}") from error


def _response(row: LlmOutput, packet: dict, cached: bool) -> dict:
    by_id = {item["id"]: item for item in packet["items"]}
    cited = sorted({c for value in row.output.values() if value
                    for entry in (value if isinstance(value, list) else [value]) for c in entry["cites"]})
    return {
        "kind": row.kind,
        "subject": row.subject,
        "model": row.model,
        "served_by": row.served_by,
        "prompt_version": row.prompt_version,
        "cached": cached,
        "usage": row.usage,  # tokens of the call that produced this text (not re-billed when cached)
        "output": row.output,
        "rejected_claims": row.rejected,
        "sources": {c: by_id[c] for c in cited},
    }


def explain(session: Session, org: OrgConfig, kind: str, subject: str, packet: dict,
            client: LLMClient, regenerate: bool = False) -> dict:
    key = (org.name, kind, subject, input_hash(packet, config.MODEL, config.PROMPT_VERSION))
    row = session.get(LlmOutput, key)
    if row is not None and not regenerate:
        return _response(row, packet, cached=True)

    task, schema, model = KINDS[kind]
    result = client.generate(system=prompts.SYSTEM, user=prompts.user_message(task, packet), schema=schema)
    try:
        validated = model.model_validate(result.data).model_dump()
    except ValidationError as error:
        raise LLMError(f"Model output did not match the {kind} schema: {error.error_count()} errors") from error
    try:
        kept, rejected = enforce(validated, ids(packet))
    except NothingGrounded as error:
        raise LLMError(str(error)) from error

    row = session.merge(LlmOutput(
        org=key[0], kind=key[1], subject=key[2], input_hash=key[3],
        model=config.MODEL, served_by=result.model, prompt_version=config.PROMPT_VERSION,
        output=kept, rejected=[r.model_dump() for r in rejected],
        usage={**result.usage, "fallback_used": result.fallback_used},
    ))
    session.commit()
    return _response(row, packet, cached=False)
