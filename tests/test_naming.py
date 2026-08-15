"""Reading a hero, a variant and a version out of a mod file name.

Mod authors drop spaces, abbreviate, use MCU names, and append the download id
Nexus adds. Getting this wrong loses a mod's hero grouping and its conflict
warnings, so the awkward real-world shapes get a test.
"""

from __future__ import annotations

import pytest

from regalia.naming import parse, slugify


@pytest.mark.parametrize(
    ("filename", "hero"),
    [
        ("AdamWarlock_Magus.7z", "Adam Warlock"),
        ("Muscular Adam Warlock - MCU Skin.7z", "Adam Warlock"),
        ("CaptAmerica_Classic.zip", "Captain America"),
        ("blackwidow-natasha-v2.7z", "Black Widow"),
        ("Doctor Strange Cape.7z", "Doctor Strange"),
        ("cloakdagger_pack.7z", "Cloak & Dagger"),
    ],
)
def test_the_hero_is_recognised(filename, hero):
    assert parse(filename).hero == hero


def test_iron_man_does_not_swallow_iron_fist():
    """Longest-first matching exists for exactly this pair."""
    assert parse("IronFist_Dragon.7z").hero == "Iron Fist"
    assert parse("IronMan_MK50.7z").hero == "Iron Man"


def test_the_bare_cap_alias_loses_to_the_longer_one():
    assert parse("CaptainAmerica_Classic.7z").hero == "Captain America"


def test_an_unknown_hero_keeps_the_whole_name():
    parsed = parse("SomeoneEntirelyNew_Skin.7z")
    assert parsed.hero == "Unknown"
    assert "Someone" in parsed.variant or "SomeoneEntirelyNew" in parsed.variant


def test_a_version_is_read_and_removed():
    parsed = parse("Loki_Helmet_V1.2.0.7z")
    assert parsed.version == "1.2.0"
    assert "1.2.0" not in parsed.variant


def test_the_load_order_suffix_is_noticed():
    """A pak without _9999999_P may not override the base game."""
    assert parse("Loki_Helmet_9999999_P.7z").has_load_order is True
    assert parse("Loki_Helmet.7z").has_load_order is False


def test_noise_words_leave_the_variant():
    parsed = parse("Muscular Hulk Skin Mod.7z")
    assert parsed.hero == "Hulk"
    assert "Skin" not in parsed.variant
    assert "Mod" not in parsed.variant


def test_slugify_is_stable_and_safe():
    assert slugify("Adam Warlock · Magus / Thong") == slugify(
        "Adam Warlock · Magus / Thong"
    )
    assert "/" not in slugify("Adam Warlock / Magus")
