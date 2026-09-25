"""Claude client. The model only ever sees an evidence packet; the response is
structured JSON that is validated and citation-checked by the caller.

Uses the official SDK on the beta messages path for the server-side refusal
fallback (`fallbacks: "default"`). A refusal arrives as HTTP 200 with
stop_reason "refusal", so stop_reason is checked before reading content.
"""

import json
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
from dotenv import find_dotenv, load_dotenv

from app.llm import config


class LLMError(Exception):
    status = 502


class LLMUnavailable(LLMError):
    """Rate limited, overloaded or unreachable: retry later."""
    status = 503


class LLMRefused(LLMError):
    """The request was declined (after any fallback)."""
    status = 503

    def __init__(self, category: str | None):
        super().__init__(f"Model declined the request (category: {category})")
        self.category = category


class LLMMisconfigured(LLMError):
    status = 500


@dataclass(frozen=True)
class LLMResult:
    data: dict  # parsed JSON (not yet schema- or citation-checked)
    model: str  # the model that served the answer (differs if a fallback ran)
    fallback_used: bool
    usage: dict = field(default_factory=dict)


class LLMClient(Protocol):
    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult: ...


class AnthropicLLM:
    def __init__(self, client: anthropic.Anthropic | None = None):
        load_dotenv(find_dotenv(usecwd=True))
        self._client = client or anthropic.Anthropic()

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult:
        try:
            response = self._client.beta.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                betas=[config.FALLBACK_BETA],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": config.EFFORT, "format": {"type": "json_schema", "schema": schema}},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError as error:
            raise LLMMisconfigured("Anthropic API key missing or invalid") from error
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as error:
            raise LLMUnavailable(str(error)) from error
        except anthropic.APIStatusError as error:
            if error.status_code >= 500:
                raise LLMUnavailable(f"Anthropic API error {error.status_code}") from error
            raise LLMError(f"Anthropic API rejected the request ({error.status_code}): {error.message}") from error

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefused(getattr(details, "category", None) if details else None)
        if response.stop_reason == "max_tokens":
            raise LLMError("Output hit max_tokens before completing")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError(f"No text block in response (stop_reason={response.stop_reason})")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise LLMError("Response was not valid JSON") from error
        usage = response.usage
        return LLMResult(
            data=data,
            model=response.model,
            fallback_used=any(b.type == "fallback" for b in response.content),
            usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
        )
