"""The user hero overlay.

The game adds a hero every season. An unknown hero parses as "Unknown", which
also loses its conflict warnings, so a user has to be able to name one without
waiting for a release.
"""

from __future__ import annotations

import tomllib

import pytest

from regalia.heroes import merge_heroes, read_overlay

BASE = {"Hulk": ("brucebanner",), "Loki": ()}


def write(tmp_path, text: str):
    path = tmp_path / "heroes.toml"
    path.write_text(text)
    return path


# -- reading -------------------------------------------------------------


def test_a_missing_file_is_not_an_error(tmp_path):
    assert read_overlay(tmp_path / "absent.toml") == {}


def test_a_heroes_table_is_read(tmp_path):
    path = write(tmp_path, '[heroes]\nUltron = ["ultron", "vision"]\n')
    assert read_overlay(path) == {"Ultron": ("ultron", "vision")}


def test_a_bare_table_is_also_accepted(tmp_path):
    path = write(tmp_path, 'Ultron = ["ultron"]\n')
    assert read_overlay(path) == {"Ultron": ("ultron",)}


def test_one_alias_may_be_a_plain_string(tmp_path):
    path = write(tmp_path, '[heroes]\nUltron = "ultron"\n')
    assert read_overlay(path) == {"Ultron": ("ultron",)}


def test_a_hero_with_no_aliases_is_allowed(tmp_path):
    path = write(tmp_path, "[heroes]\nUltron = []\n")
    assert read_overlay(path) == {"Ultron": ()}


def test_broken_toml_raises_so_the_check_can_report_it(tmp_path):
    path = write(tmp_path, "[heroes\nUltron = ]")
    with pytest.raises(tomllib.TOMLDecodeError):
        read_overlay(path)


def test_a_wrong_value_type_raises(tmp_path):
    path = write(tmp_path, "[heroes]\nUltron = 7\n")
    with pytest.raises(ValueError):
        read_overlay(path)


# -- merging -------------------------------------------------------------


def test_a_new_hero_is_added():
    merged = merge_heroes(BASE, {"Ultron": ("ultron",)})
    assert merged["Ultron"] == ("ultron",)
    assert merged["Hulk"] == ("brucebanner",)


def test_an_existing_hero_gains_aliases_without_losing_any():
    merged = merge_heroes(BASE, {"Hulk": ("banner",)})
    assert merged["Hulk"] == ("brucebanner", "banner")


def test_a_repeated_alias_appears_once():
    merged = merge_heroes(BASE, {"Hulk": ("brucebanner", "banner")})
    assert merged["Hulk"] == ("brucebanner", "banner")


def test_an_empty_overlay_changes_nothing():
    assert merge_heroes(BASE, {}) == BASE


def test_the_base_table_is_not_mutated():
    merge_heroes(BASE, {"Hulk": ("banner",)})
    assert BASE["Hulk"] == ("brucebanner",)
