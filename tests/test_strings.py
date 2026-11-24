"""All user-facing text lives in app/strings.py, ready for translation."""
import re
import string
from datetime import date, datetime
from pathlib import Path

import pytest

from app import strings
from app.strings import EN, LANGUAGES, placeholders, t

APP = Path(__file__).resolve().parent.parent / "app"
SOURCES = {p: p.read_text(encoding="utf-8") for p in APP.rglob("*.py") if p.name != "strings.py"}

# Keys built at run time, e.g. t(f"history.empty_{type_}"), and what they expand to.
DYNAMIC = {
    "history.empty_": ["expense", "income", "transfer"],
    "history.": ["all", "expense", "income", "transfer"],
    "categories.": ["expense", "income"],
    "categories.new_prompt_": ["expense", "income"],
    "error.unknown_category_": ["expense", "income"],
    "error.category_limit_": ["expense", "income"],
    "csv.": ["expense", "income", "transfer"],
    "region.": ["africa", "americas", "asia", "europe", "oceania"],
    "settings.": ["weekly_on", "weekly_off", "monthly_on", "monthly_off"],
    "gate.alert_": ["not_admin", "no_invite"],
}


def used_keys():
    static, dynamic = set(), set()
    for text in SOURCES.values():
        static |= set(re.findall(r"""\bt\(\s*["']([a-z_]+\.[a-z0-9_.]+)["']""", text))
        dynamic |= set(re.findall(r"""\bt\(\s*f["']([a-z_]+\.[a-z0-9_]*)\{""", text))
        # keys chosen inside the call too: t("recap.up" if pct > 0 else "recap.down", ...)
        static |= set(re.findall(r"""["']([a-z_]+\.[a-z0-9_]+)["']""", text)) & EN.keys()
    return static, dynamic


def test_every_key_the_code_uses_exists():
    static, dynamic = used_keys()
    assert len(static) > 250
    assert static - EN.keys() == set()
    assert dynamic <= DYNAMIC.keys(), dynamic - DYNAMIC.keys()
    for prefix in dynamic:
        for suffix in DYNAMIC[prefix]:
            assert prefix + suffix in EN, prefix + suffix


def test_every_key_is_used():
    static, dynamic = used_keys()
    expanded = {p + s for p in dynamic for s in DYNAMIC[p]}
    unused = EN.keys() - static - expanded
    assert unused == set(), unused


DUMMY = {"day": date(2026, 11, 23), "since": datetime(2026, 11, 23), "start": datetime(2026, 11, 16),
         "end": datetime(2026, 11, 23), "last": datetime(2026, 11, 22), "rate": 12.0, "size_kb": 3.0, "max": 100}


@pytest.mark.parametrize("key", sorted(EN))
def test_every_text_formats(key):
    values = {name: DUMMY.get(name, f"<{name}>") for name in placeholders(EN[key])}
    text = t(key, **values) if values else t(key)
    assert text and "{" not in text


def test_translations_have_the_same_keys_and_placeholders():
    for lang, table in LANGUAGES.items():
        assert table.keys() <= EN.keys(), lang
        for key, value in table.items():
            assert placeholders(value) == placeholders(EN[key]), (lang, key)


def test_a_missing_translation_falls_back_to_english(monkeypatch):
    monkeypatch.setitem(strings.LANGUAGES, "xx", {"menu.add": "➕ Xx"})
    assert t("menu.add", lang="xx") == "➕ Xx"
    assert t("menu.help", lang="xx") == EN["menu.help"]


SENDS = re.compile(r"""(?:reply_text|edit_message_text|\.answer|InlineKeyboardButton|KeyboardButton|ValidationError|"""
                   r"""HTTPException\(\s*\d+\s*,\s*detail=\{\s*"error"\s*:)\(?\s*f?(["'])(.*?)\1|"""
                   r"""(?:text|caption)=f?(["'])(.*?)\3""")


MACHINE_CODES = {"not_subscribed"}  # error codes the Mini App reads, never shown as text


def test_no_user_facing_text_is_written_inline():
    """Text handed to Telegram (or to a user as an error) must come from strings.t();
    a literal may only glue pieces together (emoji, punctuation, {values})."""
    offenders = []
    for path, text in SOURCES.items():
        for m in SENDS.finditer(text):
            literal = m.group(2) if m.group(2) is not None else m.group(4)
            words = re.sub(r"\{[^}]*\}|\\n", " ", literal or "")
            if re.search(r"[A-Za-z]{2,}", words) and literal not in MACHINE_CODES:
                offenders.append(f"{path.relative_to(APP)}: {literal!r}")
    assert offenders == []


def test_templates_are_valid_format_strings():
    for key, value in EN.items():
        list(string.Formatter().parse(value))   # raises on a stray { or }
