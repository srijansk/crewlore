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


# GUARDS: a key that is present but rejected is indistinguishable from a
# transient error at the call site. It must be raised as fatal, or the compiler
# skips every session and reports a successful, empty run.
def test_rejected_api_key_becomes_a_fatal_credentials_error():
    import pytest

    from lore.compile.extractor import FatalExtractionError
    from lore.compile.llm import CredentialsError, _reraise_auth_errors

    class Unauthorized(Exception):
        status_code = 401

    assert issubclass(CredentialsError, FatalExtractionError)
    with pytest.raises(CredentialsError, match="rejected the API key"):
        _reraise_auth_errors(Unauthorized(), "Anthropic")


# GUARDS: rate limits and server errors must stay retryable, not be misreported
# as a credentials problem that tells the user to go check their key.
def test_transient_status_codes_are_not_treated_as_credentials_failures():
    from lore.compile.llm import _reraise_auth_errors

    class RateLimited(Exception):
        status_code = 429

    _reraise_auth_errors(RateLimited(), "Anthropic")  # returns, caller re-raises
