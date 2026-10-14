"""Model-written text is cleaned of terminal escapes and control characters before it is
stored or served; newlines and tabs are kept, and an optional cap marks truncation."""

from lore.text import sanitize_text


def test_strips_ansi_colours_and_osc_hyperlinks():
    assert sanitize_text("\x1b[31mred\x1b[0m text") == "red text"
    assert sanitize_text("\x1b]8;;https://x\x07link\x1b]8;;\x07") == "link"


def test_strips_control_characters_but_keeps_newlines_and_tabs():
    assert sanitize_text("a\x00b\x07c\td\ne\x7f") == "abc\td\ne"


def test_normalises_carriage_returns():
    assert sanitize_text("one\r\ntwo\rthree") == "one\ntwo\nthree"


def test_caps_length_with_an_ellipsis():
    assert sanitize_text("x" * 10, limit=4) == "xxxx…"
    assert sanitize_text("short", limit=10) == "short"


def test_plain_text_is_unchanged():
    assert sanitize_text("Dedupe on the idempotency key.") == "Dedupe on the idempotency key."
