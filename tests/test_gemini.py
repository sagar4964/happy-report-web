"""Gemini connection tests: no internet, no key needed."""
import pytest
import requests
from app.ai import get_provider
from app.ai.base import AIError
from app.ai.gemini_provider import GeminiProvider
from app.ai.openai_provider import OpenAIProvider


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def ok_payload(text="hello", finish="STOP", version="gemini-test-1"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
            "modelVersion": version}


@pytest.fixture
def gemini_configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-not-real")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setattr("app.ai.gemini_provider.time.sleep", lambda s: None)


def test_gemini_needs_key_and_model(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    with pytest.raises(AIError) as e:
        GeminiProvider()
    assert e.value.code == "config"


def test_gemini_refuses_odd_model_names(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_MODEL", "../evil model")
    with pytest.raises(AIError) as e:
        GeminiProvider()
    assert e.value.code == "config"


def test_gemini_success_builds_the_right_request(gemini_configured, monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return FakeResponse(200, ok_payload("the answer"))
    monkeypatch.setattr("app.ai.gemini_provider.requests.post", fake_post)
    result = GeminiProvider().generate("SYSTEM TEXT", "USER TEXT")
    assert result.text == "the answer" and result.model == "gemini-test-1"
    assert seen["url"].endswith("/models/gemini-test:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "fake-key-not-real"
    assert "key=" not in seen["url"]  # the key is never put in the web address
    assert seen["json"]["system_instruction"]["parts"][0]["text"] == "SYSTEM TEXT"
    assert seen["json"]["contents"][0]["parts"][0]["text"] == "USER TEXT"


def test_models_prefix_is_removed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_MODEL", "models/gemini-test")
    assert GeminiProvider().model == "gemini-test"


@pytest.mark.parametrize("status,code", [
    (400, "bad_request"), (401, "auth"), (403, "auth"), (404, "model"), (429, "rate_limit"), (500, "server"),
])
def test_gemini_error_messages(gemini_configured, monkeypatch, status, code):
    monkeypatch.setattr("app.ai.gemini_provider.requests.post",
                        lambda *a, **k: FakeResponse(status, {"error": "secret details"}))
    with pytest.raises(AIError) as e:
        GeminiProvider().generate("s", "u")
    assert e.value.code == code
    assert "secret details" not in e.value.user_message


def test_gemini_retries_busy_then_succeeds(gemini_configured, monkeypatch):
    replies = [FakeResponse(429, {}), FakeResponse(503, {}), FakeResponse(200, ok_payload("fine"))]
    monkeypatch.setattr("app.ai.gemini_provider.requests.post", lambda *a, **k: replies.pop(0))
    assert GeminiProvider().generate("s", "u").text == "fine"


def test_gemini_timeout_and_network(gemini_configured, monkeypatch):
    def timeout(*a, **k):
        raise requests.Timeout()

    def down(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr("app.ai.gemini_provider.requests.post", timeout)
    with pytest.raises(AIError) as e:
        GeminiProvider().generate("s", "u")
    assert e.value.code == "timeout"
    monkeypatch.setattr("app.ai.gemini_provider.requests.post", down)
    with pytest.raises(AIError) as e:
        GeminiProvider().generate("s", "u")
    assert e.value.code == "network"


@pytest.mark.parametrize("payload,code", [
    ({"candidates": []}, "blocked"),
    ({}, "blocked"),
    (ok_payload("cut", finish="MAX_TOKENS"), "truncated"),
    (ok_payload("   "), "empty"),
    ({"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}, "blocked"),
    ({"candidates": ["not a dict"]}, "format"),
])
def test_gemini_bad_replies(gemini_configured, monkeypatch, payload, code):
    monkeypatch.setattr("app.ai.gemini_provider.requests.post", lambda *a, **k: FakeResponse(200, payload))
    with pytest.raises(AIError) as e:
        GeminiProvider().generate("s", "u")
    assert e.value.code == code


def test_thinking_parts_are_not_part_of_the_answer(gemini_configured, monkeypatch):
    payload = {"candidates": [{"content": {"parts": [
        {"text": "private reasoning", "thought": True}, {"text": "Visible answer"}]},
        "finishReason": "STOP"}]}
    monkeypatch.setattr("app.ai.gemini_provider.requests.post", lambda *a, **k: FakeResponse(200, payload))
    assert GeminiProvider().generate("s", "u").text == "Visible answer"


def test_provider_choice_follows_the_setting(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("OPENAI_MODEL", "x")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    assert isinstance(get_provider(), GeminiProvider)
    monkeypatch.setenv("AI_PROVIDER", "OpenAI ")
    assert isinstance(get_provider(), OpenAIProvider)
    monkeypatch.setenv("AI_PROVIDER", "nonsense")
    with pytest.raises(AIError) as e:
        get_provider()
    assert e.value.code == "config"
