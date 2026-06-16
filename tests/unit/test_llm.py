"""Provider wiring: build_complete routes provider config to a complete() seam,
errors clearly when credentials/config are missing, and supports a local
OpenAI-compatible endpoint. No network calls — we only check construction,
routing, and the shape of the errors a misconfigured user would hit.
"""

import pytest

from lore.compile.llm import CredentialsError, build_complete


def test_anthropic_is_default_and_needs_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CredentialsError) as exc:
        build_complete({})  # empty config -> default provider anthropic
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_anthropic_with_key_builds_a_callable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    complete = build_complete({"model": {"provider": "anthropic", "name": "claude-sonnet-4-6"}})
    assert callable(complete)


def test_openai_without_key_errors_clearly(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CredentialsError) as exc:
        build_complete({"model": {"provider": "openai"}})
    assert "OPENAI_API_KEY" in str(exc.value)


def test_local_provider_requires_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CredentialsError) as exc:
        build_complete({"model": {"provider": "local"}})
    assert "base_url" in str(exc.value)


def test_local_provider_with_base_url_builds_without_a_key(monkeypatch):
    # The whole point of a local endpoint: no hosted key required.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    complete = build_complete(
        {"model": {"provider": "local", "base_url": "http://localhost:11434/v1"}}
    )
    assert callable(complete)


def test_unknown_provider_errors_with_actionable_message():
    with pytest.raises(CredentialsError) as exc:
        build_complete({"model": {"provider": "mistral-cloud"}})
    msg = str(exc.value)
    assert "Unknown model provider" in msg
    # The message must not send the user down a dead end — it names the real options.
    assert "anthropic" in msg and "openai" in msg and "local" in msg
