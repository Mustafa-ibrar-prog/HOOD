"""Exercise AnthropicAnalyzer through the real SDK against a mock HTTP transport.

This verifies the request we build (model, structured-output schema, effort,
fallbacks beta) serialises correctly and that streamed responses are parsed.
It does NOT prove the live API accepts it — that needs a real key.
"""
import json

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from app.analysis import llm  # noqa: E402
from app.config import settings  # noqa: E402

MOMENTS = {"moments": [{
    "start_id": 1, "end_id": 3, "content_type": "debate", "hook_quote": "Hello.",
    "scores": {"hook": 80, "emotion": 70, "clarity": 75, "payoff": 60, "pacing": 70, "shareability": 65},
    "explanation": "e", "selection_reason": "r",
    "platforms": {p: {"title": "t", "description": "d", "hashtags": ["#a"]} for p in llm.PLATFORMS},
}]}


def _sse(stop_reason="end_turn", text=None):
    text = json.dumps(MOMENTS) if text is None else text
    events = [
        ("message_start", {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant",
                                                                  "model": "claude-opus-5-5", "content": [], "stop_reason": None,
                                                                  "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 50}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()


def _analyzer(monkeypatch, handler):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    a = llm.AnthropicAnalyzer()
    a.client = anthropic.Anthropic(api_key="test-key", base_url="http://mock.local", max_retries=0,
                                   http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return a


def test_request_shape_and_parse(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse())

    a = _analyzer(monkeypatch, handler)
    out = a._complete("sys", "user")
    assert out == MOMENTS
    body = seen["body"]
    assert body["model"] == settings.anthropic_model
    assert body["stream"] is True
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"] == llm.MOMENTS_SCHEMA
    assert body["output_config"]["effort"] == settings.anthropic_effort
    assert "thinking" not in body and "temperature" not in body
    if settings.anthropic_model in llm.AnthropicAnalyzer._FALLBACK_MODELS and settings.anthropic_fallbacks:
        assert body["fallbacks"] == "default"
        assert "server-side-fallback-2026-07-01" in seen["headers"].get("anthropic-beta", "")
    assert seen["headers"]["x-api-key"] == "test-key"


def test_refusal_and_truncation_raise(monkeypatch):
    a = _analyzer(monkeypatch, lambda r: httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse("refusal", "")))
    with pytest.raises(llm.AnalysisError, match="declined"):
        a._complete("s", "u")
    a = _analyzer(monkeypatch, lambda r: httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse("max_tokens", "{")))
    with pytest.raises(llm.AnalysisError) as e:
        a._complete("s", "u")
    assert e.value.retryable


@pytest.mark.parametrize("status,retryable,match", [(401, False, "API key"), (429, True, "rate limit"), (529, True, "529"), (400, False, "rejected")])
def test_http_errors_map_to_analysis_errors(monkeypatch, status, retryable, match):
    body = {"type": "error", "error": {"type": "x", "message": "nope"}}
    a = _analyzer(monkeypatch, lambda r: httpx2.Response(status, json=body))
    with pytest.raises(llm.AnalysisError, match=match) as e:
        a._complete("s", "u")
    assert e.value.retryable is retryable
