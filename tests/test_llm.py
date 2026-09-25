"""LLM layer, fully offline: evidence packets, the citation check, the Claude
client's refusal/error handling (fake SDK), storage, and the endpoints (fake
model). No test ever calls the real API."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.llm import config
from app.llm.citations import NothingGrounded, enforce
from app.llm.client import AnthropicLLM, LLMError, LLMRefused, LLMResult, LLMUnavailable
from app.llm.packet import canonical, ids, release_packet, repro_packet
from app.llm.schemas import RELEASE_SUMMARY_SCHEMA, REPRO_NARRATIVE_SCHEMA
from scripts.demo import scenario as sc
from tests.test_release_impact import IMPACTS, _impact
from tests.test_reproduction import REPROS, _reproduce

# ------------------------------------------------------------------ packets

ALL_RELEASE_PACKETS = {c: release_packet(_impact(s.release)) for c, s in IMPACTS.items()}
ALL_REPRO_PACKETS = {c: repro_packet(_reproduce(s.incident)) for c, s in REPROS.items()}


@pytest.mark.parametrize("packet", [*ALL_RELEASE_PACKETS.values(), *ALL_REPRO_PACKETS.values()])
def test_packets_carry_no_user_or_installation_identifiers(packet: dict) -> None:
    text = canonical(packet)
    for marker in ("account-case-", "install-case-", "user_id", "installation_id"):
        assert marker not in text, marker


def test_packet_ids_are_unique_and_stable() -> None:
    for case, spec in IMPACTS.items():
        packet = ALL_RELEASE_PACKETS[case]
        assert len(ids(packet)) == len(packet["items"])
        assert canonical(packet) == canonical(release_packet(_impact(spec.release)))


def test_release_packet_exposes_the_facts_a_summary_needs() -> None:
    packet = {i["id"]: i for i in ALL_RELEASE_PACKETS["RI2"]["items"]}
    assert packet["metric-health"]["crash_free"] == pytest.approx(0.9)
    assert [f["code"] for k, f in sorted(packet.items()) if k.startswith("finding-")][0] == "CRASH_RATE_REGRESSION"
    assert packet["issue-F1"]["attribution"] and packet["issue-F2"]["attribution"] == []


def test_repro_packet_keeps_unknowns_and_variation_explicit() -> None:
    packet = {i["id"]: i for i in ALL_REPRO_PACKETS["RP2"]["items"]}
    assert packet["precondition-push.os_permission"]["value"] == "DENIED"
    assert "varies-profile.consistent" in packet
    assert any(v["code"] == "BREADCRUMBS_TRUNCATED" for k, v in packet.items() if k.startswith("gap-"))
    long_variant = max((v for k, v in packet.items() if k.startswith("variant-")), key=lambda v: v["prefix_length"])
    assert len(long_variant["prefix"]) == 7  # 3 + "... more ..." + 3: long trails don't flood the prompt


# ---------------------------------------------------------------- citations

VALID = {"finding-1", "metric-health"}


def _c(text, *cites):
    return {"text": text, "cites": list(cites)}


def test_citation_check_keeps_grounded_and_reports_the_rest() -> None:
    output = {"headline": _c("Crash rate fell.", "metric-health"),
              "claims": [_c("ok", "finding-1"), _c("uncited"), _c("made up", "finding-9")],
              "hypotheses": [], "caveats": []}
    kept, rejected = enforce(output, VALID)
    assert kept["headline"]["text"] == "Crash rate fell." and [c["text"] for c in kept["claims"]] == ["ok"]
    assert [(r.text, r.reason) for r in rejected] == [("uncited", "NO_CITATION"), ("made up", "UNKNOWN_ID")]


def test_citation_check_drops_an_ungrounded_headline_but_keeps_the_rest() -> None:
    kept, rejected = enforce({"headline": _c("x", "nope"), "claims": [_c("ok", "finding-1")]}, VALID)
    assert kept["headline"] is None and rejected[0].field == "headline"


def test_nothing_grounded_is_an_error_not_empty_prose() -> None:
    with pytest.raises(NothingGrounded):
        enforce({"headline": _c("x"), "claims": [_c("y", "nope")]}, VALID)


# ------------------------------------------------- client (fake SDK objects)


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _sdk(response=None, error=None):
    messages = FakeMessages(response, error)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def _response(stop_reason="end_turn", content=None, model="claude-opus-5", stop_details=None):
    return SimpleNamespace(stop_reason=stop_reason, stop_details=stop_details, model=model,
                           content=content if content is not None else [],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=20))


def _text(data) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=json.dumps(data))


def test_client_sends_fallbacks_structured_output_and_adaptive_thinking() -> None:
    sdk, messages = _sdk(_response(content=[_text({"a": 1})]))
    result = AnthropicLLM(sdk).generate(system="s", user="u", schema=RELEASE_SUMMARY_SCHEMA)
    (call,) = messages.calls
    assert call["model"] == config.MODEL and call["fallbacks"] == "default"
    assert call["betas"] == [config.FALLBACK_BETA] and call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": RELEASE_SUMMARY_SCHEMA}
    assert result.data == {"a": 1} and not result.fallback_used


def test_client_reports_which_model_served_a_fallback() -> None:
    sdk, _ = _sdk(_response(model="claude-opus-4-8", content=[SimpleNamespace(type="fallback"), _text({})]))
    result = AnthropicLLM(sdk).generate(system="s", user="u", schema=REPRO_NARRATIVE_SCHEMA)
    assert result.fallback_used and result.model == "claude-opus-4-8"


def test_refusal_is_checked_before_reading_content() -> None:
    sdk, _ = _sdk(_response(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")))
    with pytest.raises(LLMRefused) as caught:
        AnthropicLLM(sdk).generate(system="s", user="u", schema={})
    assert caught.value.category == "cyber" and caught.value.status == 503


@pytest.mark.parametrize("response", [
    _response(stop_reason="max_tokens", content=[_text({})]),
    _response(content=[SimpleNamespace(type="text", text="not json")]),
    _response(content=[]),
])
def test_incomplete_or_invalid_output_is_an_error(response) -> None:
    sdk, _ = _sdk(response)
    with pytest.raises(LLMError):
        AnthropicLLM(sdk).generate(system="s", user="u", schema={})


def test_rate_limit_maps_to_unavailable() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None)
    sdk, _ = _sdk(error=error)
    with pytest.raises(LLMUnavailable):
        AnthropicLLM(sdk).generate(system="s", user="u", schema={})


# ------------------------------------------------ fake model for the service


class FakeLLM:
    """Answers from the packet in the prompt, citing real (or deliberately bad) ids."""

    def __init__(self, mode: str = "good"):
        self.mode, self.calls = mode, 0

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult:
        self.calls += 1
        packet = json.loads(user[user.index("{"):])
        first = packet["items"][0]["id"]
        cite = {"good": [first], "some_bad": [first], "all_bad": ["no-such-id"]}.get(self.mode, [first])
        single = next(k for k, v in schema["properties"].items() if v.get("type") == "object")
        lists = [k for k, v in schema["properties"].items() if v.get("type") == "array"]
        data = {single: {"text": f"{self.mode} {single}", "cites": cite},
                **{name: [{"text": f"{name} ok", "cites": cite}] for name in lists}}
        if self.mode == "some_bad":
            data[lists[0]].append({"text": "invented", "cites": ["finding-999"]})
        if self.mode == "invalid_schema":
            data = {"unexpected": True}
        return LLMResult(data=data, model="claude-opus-5", fallback_used=False, usage={"input_tokens": 1})


@pytest.fixture()
def api(monkeypatch):
    """Seeded DB + ingested demo data + the API with a swappable fake model."""
    from fastapi.testclient import TestClient

    from app.api import incidents, releases
    from app.main import app
    from app.seed import seed
    from tests.test_incident_ingest_api import _ingest

    seed()
    _ingest()
    fake = {"client": FakeLLM()}
    app.dependency_overrides[releases.llm_client] = lambda: fake["client"]
    app.dependency_overrides[incidents.llm_client] = lambda: fake["client"]
    yield TestClient(app), fake
    app.dependency_overrides.clear()


pytestmark_db = pytest.mark.usefixtures("_truncate_incident_tables", "_truncate_state_observation")


@pytestmark_db
def test_summary_is_generated_once_then_served_from_storage(api) -> None:
    client, fake = api
    first = client.get("/v1/releases/1.2.0/summary").json()
    second = client.get("/v1/releases/1.2.0/summary").json()
    assert fake["client"].calls == 1
    assert (first["cached"], second["cached"]) == (False, True)
    assert first["output"] == second["output"] and first["output"]["headline"]
    assert set(first["sources"]) == {"release"}  # every cited id resolves to a packet item


@pytestmark_db
def test_regenerate_and_prompt_version_change_call_the_model_again(api, monkeypatch) -> None:
    client, fake = api
    client.get("/v1/incidents/F6/narrative")
    client.get("/v1/incidents/F6/narrative?regenerate=true")
    monkeypatch.setattr(config, "PROMPT_VERSION", "test-bump")
    third = client.get("/v1/incidents/F6/narrative").json()
    assert fake["client"].calls == 3 and third["prompt_version"] == "test-bump"


@pytestmark_db
def test_invented_citations_are_dropped_and_reported(api) -> None:
    client, fake = api
    fake["client"] = FakeLLM("some_bad")
    body = client.get("/v1/incidents/F1/narrative").json()
    assert [(r["text"], r["reason"]) for r in body["rejected_claims"]] == [("invented", "UNKNOWN_ID")]
    assert all("invented" != s["text"] for s in body["output"]["steps_prose"])


@pytestmark_db
@pytest.mark.parametrize("mode", ["all_bad", "invalid_schema"])
def test_ungrounded_or_malformed_output_is_502_and_not_stored(api, mode) -> None:
    from app.db import SessionLocal
    from app.models import LlmOutput

    client, fake = api
    fake["client"] = FakeLLM(mode)
    assert client.get("/v1/releases/1.3.0/summary").status_code == 502
    with SessionLocal() as session:
        assert session.query(LlmOutput).count() == 0


@pytestmark_db
def test_unknown_release_and_incident_are_404_without_calling_the_model(api) -> None:
    client, fake = api
    assert client.get("/v1/releases/9.9.9/summary").status_code == 404
    assert client.get("/v1/incidents/never/narrative").status_code == 404
    assert fake["client"].calls == 0
