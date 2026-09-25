"""Deterministic grounding check: every sentence the model writes must cite at
least one id that exists in the evidence packet. Failing sentences are dropped
and reported -- never silently kept."""

from pydantic import BaseModel


class Rejected(BaseModel):
    field: str
    text: str
    cites: list[str]
    reason: str  # NO_CITATION | UNKNOWN_ID


class NothingGrounded(Exception):
    """Every sentence failed the check: returning empty prose would mislead."""


def _check(item: dict, valid: set[str]) -> str | None:
    if not item["cites"]:
        return "NO_CITATION"
    if any(c not in valid for c in item["cites"]):
        return "UNKNOWN_ID"
    return None


def enforce(output: dict, valid_ids: set[str]) -> tuple[dict, list[Rejected]]:
    kept: dict = {}
    rejected: list[Rejected] = []
    grounded = 0
    for field, value in output.items():
        entries = value if isinstance(value, list) else [value]
        good = []
        for entry in entries:
            reason = _check(entry, valid_ids)
            if reason:
                rejected.append(Rejected(field=field, text=entry["text"], cites=entry["cites"], reason=reason))
            else:
                good.append(entry)
        grounded += len(good)
        kept[field] = good if isinstance(value, list) else (good[0] if good else None)
    if grounded == 0:
        raise NothingGrounded(f"All {len(rejected)} sentences failed the citation check")
    return kept, rejected
