"""Text hygiene for model output and for anything handed to a person or an agent.

Claims are written by a model from transcripts and pull-request threads that other
people and tools wrote. Escape sequences and invisible characters in that text would
survive into the book, the CLI output and the MCP payload, where they can restyle a
terminal, hide content, or reorder what a reader sees. They carry no knowledge, so
they are removed at the point a claim is built and again at the point it is served.
"""

from __future__ import annotations

import re

# ANSI escape sequences: colours and cursor moves (CSI), then OSC strings such as
# terminal hyperlinks, terminated by BEL or ST.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

# Characters with no visible width that can hide text or reorder what a reader sees:
# C0 controls except tab and newline, DEL and the C1 range, the bidirectional
# embedding, override and isolate controls behind Trojan-source attacks, zero-width
# space, word joiner, soft hyphen and byte-order mark, the invisible operators,
# deprecated format controls, interlinear annotation marks and Mongolian vowel
# separator, and the Unicode tag block that smuggles ASCII invisibly. Zero-width
# joiner and non-joiner stay: Indic and Persian text and emoji sequences depend on
# them, and so do the left-to-right and right-to-left marks that mixed-direction
# text needs.
_INVISIBLE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u00ad\u200b\u2060\u202a-\u202e"
    "\u2061-\u2064\u2066-\u2069\u206a-\u206f\ufeff\ufff9-\ufffb\u180e\U000e0000-\U000e007f]"
)

# Every line break a model or a web form can produce, folded to one newline.
_LINE_BREAKS = ("\r\n", "\r", "\u2028", "\u2029")

# The one legitimate use of tag characters: a subdivision flag is the black flag
# followed by tag letters and a tag terminator. Matched first so it survives the strip.
_SUBDIVISION_FLAG = "\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f"
_STRIP = re.compile(f"({_SUBDIVISION_FLAG})|{_INVISIBLE.pattern}")


def sanitize_text(text: str | None) -> str:
    """Strip escape sequences and invisible characters; fold line breaks to newlines.

    Newlines and tabs are kept, so a multi-line quote stays multi-line in a JSON
    payload. Use `sanitize_line` for anything printed as one line. `None` is treated
    as empty text, so optional fields can be passed straight through; any other
    non-string is rendered with `str`, so a numeric login cannot crash a hook.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    cleaned = _ANSI.sub("", text)
    for sequence in _LINE_BREAKS:
        cleaned = cleaned.replace(sequence, "\n")
    return _STRIP.sub(lambda m: m.group(1) or "", cleaned)


def sanitize_line(text: str | None) -> str:
    """`sanitize_text`, then every run of whitespace, newlines included, becomes one space.

    Claim statements, scopes, topics and actions are single-line fields: a newline
    inside one would let a claim print as two, forging a second claim line in the
    CLI, the book and the prompt.
    """
    return " ".join(sanitize_text(text).split())
