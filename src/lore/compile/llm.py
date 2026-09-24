"""Provider abstraction so lore is genuinely BYO-key / local-first: point it at
Anthropic, OpenAI, or any OpenAI-compatible endpoint you run yourself (Ollama,
LM Studio, vLLM, …) via `provider: local` + `base_url`. Nothing routes through
any lore-operated infrastructure because there is none.

The default provider (Anthropic) ships as a base dependency so the headline
`pipx install crewlore` → `lore compile` path works with just a key. The OpenAI
SDK is an optional extra; if a provider needs an SDK that isn't installed, we
raise a clear, actionable error instead of a raw ImportError traceback.
"""

from __future__ import annotations

import os

from lore.compile.extractor import Complete, FatalExtractionError

# Provider status codes that mean "your credentials are wrong", not "try again".
_AUTH_STATUS = {401, 403}


class CredentialsError(FatalExtractionError):
    """Raised when model credentials / config are missing, invalid, or a provider is unknown."""


def _reraise_auth_errors(exc: Exception, provider_hint: str) -> None:
    """Translate a provider auth rejection into a fatal, actionable error.

    A key that is present but rejected is otherwise indistinguishable from a
    transient per-session failure, and the compiler would skip every session and
    report a successful run that produced nothing.
    """
    if getattr(exc, "status_code", None) in _AUTH_STATUS:
        raise CredentialsError(
            f"{provider_hint} rejected the API key ({exc.__class__.__name__}). "
            "Check the key is current and has access to the configured model."
        ) from exc


def build_complete(config: dict) -> Complete:
    model_cfg = (config or {}).get("model", {}) or {}
    provider = model_cfg.get("provider", "anthropic")
    name = model_cfg.get("name")
    base_url = model_cfg.get("base_url")

    if provider == "anthropic":
        return _anthropic_complete(name or "claude-sonnet-4-6")
    if provider == "openai":
        return _openai_complete(name or "gpt-4o")
    if provider in ("local", "openai-compatible"):
        if not base_url:
            raise CredentialsError(
                "Provider 'local' needs `model.base_url` in .lore/config.yaml — point it at "
                "any OpenAI-compatible endpoint (e.g. http://localhost:11434/v1 for Ollama, "
                "or your LM Studio / vLLM server)."
            )
        return _openai_complete(name or "local-model", base_url=base_url)
    raise CredentialsError(
        f"Unknown model provider '{provider}'. Use 'anthropic', 'openai', or 'local' "
        "(an OpenAI-compatible endpoint configured via `model.base_url`)."
    )


def _anthropic_complete(model: str) -> Complete:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise CredentialsError(
            "No ANTHROPIC_API_KEY set. Export an API key, switch to `model.provider: openai` "
            "(with OPENAI_API_KEY), or run a local model with `model.provider: local` + "
            "`model.base_url` in .lore/config.yaml. crewlore is BYO-key; nothing routes through us."
        )

    def complete(prompt: str) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - anthropic is a base dependency
            raise CredentialsError(
                "The Anthropic SDK isn't importable. Reinstall crewlore, or: "
                "pip install 'anthropic>=0.39'."
            ) from exc

        client = anthropic.Anthropic()
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=8192,
                temperature=0,  # deterministic — extraction is structured-output, not creative
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            _reraise_auth_errors(exc, "Anthropic")
            raise
        return "".join(block.text for block in msg.content if block.type == "text")

    return complete


def _openai_complete(model: str, *, base_url: str | None = None) -> Complete:
    local = base_url is not None
    if not local and not os.environ.get("OPENAI_API_KEY"):
        raise CredentialsError(
            "No OPENAI_API_KEY set. Export an API key, or run a local OpenAI-compatible model "
            "by setting `model.provider: local` and `model.base_url` in .lore/config.yaml. "
            "crewlore is BYO-key; nothing routes through us."
        )

    def complete(prompt: str) -> str:
        try:
            import openai
        except ImportError as exc:
            raise CredentialsError(
                "The OpenAI SDK isn't installed (needed for the 'openai' and 'local' "
                "providers). Install it with: pipx inject crewlore openai   "
                "(or pip install 'crewlore[openai]')."
            ) from exc

        if base_url:
            # Local OpenAI-compatible servers usually ignore the key, but the SDK requires one.
            client = openai.OpenAI(
                base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "not-needed")
            )
        else:
            client = openai.OpenAI()
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,  # deterministic — extraction is structured-output, not creative
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            _reraise_auth_errors(exc, "OpenAI" if not base_url else base_url)
            raise
        return resp.choices[0].message.content or ""

    return complete
