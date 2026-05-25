"""Provider abstraction so lore is genuinely BYO-key / local-first: point it at
Anthropic, OpenAI, or anything that can answer a `complete(prompt) -> str` call.
Nothing routes through any lore-operated infrastructure because there is none.

SDKs are imported lazily so the package installs without them, and a missing key
fails loudly with a clear message rather than silently producing no claims.
"""

from __future__ import annotations

import os

from lore.compile.extractor import Complete


class CredentialsError(RuntimeError):
    """Raised when no usable model credentials are configured."""


def build_complete(config: dict) -> Complete:
    model_cfg = (config or {}).get("model", {}) or {}
    provider = model_cfg.get("provider", "anthropic")
    name = model_cfg.get("name")

    if provider == "anthropic":
        return _anthropic_complete(name or "claude-sonnet-4-6")
    if provider == "openai":
        return _openai_complete(name or "gpt-4o")
    raise CredentialsError(f"Unknown model provider '{provider}'.")


def _anthropic_complete(model: str) -> Complete:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise CredentialsError(
            "No ANTHROPIC_API_KEY set. Export an API key, or set model.provider to a "
            "local provider in .lore/config.yaml. lore is BYO-key; nothing routes through us."
        )

    def complete(prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if block.type == "text")

    return complete


def _openai_complete(model: str) -> Complete:
    if not os.environ.get("OPENAI_API_KEY"):
        raise CredentialsError(
            "No OPENAI_API_KEY set. Export an API key, or set model.provider to a "
            "local provider in .lore/config.yaml. lore is BYO-key; nothing routes through us."
        )

    def complete(prompt: str) -> str:
        import openai

        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""

    return complete
