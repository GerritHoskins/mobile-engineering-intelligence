"""LLM settings. The model and effort are overridable per environment; the
prompt version is part of every cache key, so changing a prompt means bumping
it (stored outputs for the old version are then simply not reused)."""

import os

MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")
EFFORT = os.environ.get("LLM_EFFORT", "high")
MAX_TOKENS = 16000  # non-streaming: stays well under the SDK's HTTP timeout
PROMPT_VERSION = "2026-09-25.1"
# Server-side refusal fallback: a policy decline is re-run on Anthropic's
# recommended model for that refusal category (Claude API only).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
