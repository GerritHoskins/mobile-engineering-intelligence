"""Prompts. Bump config.PROMPT_VERSION whenever a prompt changes."""

import json

SYSTEM = """You write short explanations for mobile engineers from a verified evidence packet.

The packet is the only source of truth. It was produced by deterministic analysis of \
Sentry, Jira and git data; you are explaining it, not investigating.

Rules:
- Every sentence you produce must cite the ids of the packet items it rests on, in its \
`cites` list. Cite only ids that appear in the packet.
- Do not add facts, numbers, causes or recommendations the packet does not support. If \
something is UNKNOWN, NOT_COMPUTED, varies between events, or is listed as a gap, say so \
plainly rather than filling it in.
- A suspect commit is a lead, not a proven cause. Phrase attributions accordingly.
- Write for a busy engineer: concrete, specific, no filler. Plain text only (no markdown)."""

RELEASE_TASK = """Summarize the impact of this release.

- headline: one sentence on what happened in this release.
- claims: the key facts (health change, new or regressed issues and what they are \
attributed to, what changed), one per item.
- hypotheses: the most plausible explanations the evidence supports, as hypotheses.
- caveats: what the evidence cannot tell us (unknowns, small samples, unattributed issues).

Evidence packet:
"""

REPRO_TASK = """Explain how to reproduce this incident.

- summary: one sentence on what the incident is and when it happens.
- steps_prose: the reproduction steps in order, in plain words.
- conditions: the preconditions to set up, and conditions that vary and so are not required.
- missing_evidence_questions: questions whose answers would close the gaps and unknowns.

Evidence packet:
"""


def user_message(task: str, packet: dict) -> str:
    return task + json.dumps(packet, indent=1, sort_keys=True, default=str)
