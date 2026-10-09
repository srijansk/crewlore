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
# ...and codes that mean "this request will be rejected every time": a bad model
# name, a parameter the model does not accept. Retrying per session is pointless.
_REQUEST_STATUS = {400, 404}


class CredentialsError(FatalExtractionError):
    """Raised when model credentials / config are missing, invalid, or a provider is unknown."""


def _reraise_fatal_errors(exc: Exception, provider_hint: str) -> None:
    """Translate a provider rejection that will recur on every session into a fatal error.

    A key that is rejected, or a request the model refuses outright (unknown
    model name, unsupported parameter), is otherwise indistinguishable from a
    transient per-session failure — the compiler would skip every session and
    report a successful run that produced nothing.
    """
    status = getattr(exc, "status_code", None)
    if status in _AUTH_STATUS:
        raise CredentialsError(
            f"{provider_hint} rejected the API key ({exc.__class__.__name__}). "
            "Check the key is current and has access to the configured model."
        ) from exc
    if status in _REQUEST_STATUS:
        detail = getattr(exc, "message", None) or str(exc)
        raise FatalExtractionError(
            f"{provider_hint} rejected the request ({exc.__class__.__name__}): {detail}. "
            "Check `model.name` and `model.temperature` in .lore/config.yaml."
        ) from exc


def _sampling(model_cfg: dict) -> dict:
    """Optional sampling parameters, sent only when configured.

    Nothing is sent by default: current Claude models reject non-default
    sampling parameters outright, and a fixed temperature never guaranteed
    deterministic extraction anyway. Set `model.temperature` in config to pass
    one to providers that accept it.
    """
    temperature = (model_cfg or {}).get("temperature")
    return {} if temperature is None else {"temperature": float(temperature)}


def build_complete(config: dict) -> Complete:
    model_cfg = (config or {}).get("model", {}) or {}
    provider = model_cfg.get("provider", "anthropic")
    name = model_cfg.get("name")
    base_url = model_cfg.get("base_url")

    sampling = _sampling(model_cfg)
    if provider == "anthropic":
        return _anthropic_complete(name or "claude-sonnet-5-5", sampling=sampling)
    if provider == "openai":
        return _openai_complete(name or "gpt-4o", sampling=sampling)
    if provider in ("local", "openai-compatible"):
        if not base_url:
            raise CredentialsError(
                "Provider 'local' needs `model.base_url` in .lore/config.yaml — point it at "
                "any OpenAI-compatible endpoint (e.g. http://localhost:11434/v1 for Ollama, "
                "or your LM Studio / vLLM server)."
            )
        return _openai_complete(name or "local-model", base_url=base_url, sampling=sampling)
    raise CredentialsError(
        f"Unknown model provider '{provider}'. Use 'anthropic', 'openai', or 'local' "
        "(an OpenAI-compatible endpoint configured via `model.base_url`)."
    )


def _anthropic_complete(model: str, *, sampling: dict | None = None) -> Complete:
    sampling = sampling or {}
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
                messages=[{"role": "user", "content": prompt}],
                **sampling,
            )
        except Exception as exc:
            _reraise_fatal_errors(exc, "Anthropic")
            raise
        return "".join(block.text for block in msg.content if block.type == "text")

    return complete


def _openai_complete(
    model: str, *, base_url: str | None = None, sampling: dict | None = None
) -> Complete:
    sampling = sampling or {}
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
                messages=[{"role": "user", "content": prompt}],
                **sampling,
            )
        except Exception as exc:
            _reraise_fatal_errors(exc, "OpenAI" if not base_url else base_url)
            raise
        return resp.choices[0].message.content or ""

    return complete
