"""Naming a mod by the character its pak changes.

Mod authors name files freely. "PANTS-4245-1-0.7z" and "one-3506.7z" are real
archive names from a real library, and neither says which hero it is for. The
container does say: its asset paths carry the character id. Nothing ships a map
from those ids to names, so the tool learns it from mods it managed to name some
other way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from regalia import heroes
from regalia.catalog import Catalog
from regalia.model import Component, Mod

STRANGE = "/marvel/content/marvel/characters/1018/1018001/meshes/sk_1018_1018001.uasset"
MAGNETO = "/marvel/content/marvel/characters/1037/1037300/meshes/sk_1037_1037300.uasset"
BOTH = [STRANGE, MAGNETO]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(heroes, "CHARACTERS_FILE", tmp_path / "characters.json")
    monkeypatch.setattr(heroes, "DATA_DIR", tmp_path)
    heroes.forget_characters()
    yield
    heroes.forget_characters()


def mod(hero: str, assets: list[str], slug: str = "x") -> Mod:
    return Mod(
        slug=slug,
        hero=hero,
        variant="",
        version=None,
        nexus_id=None,
        source=Path(f"/tmp/{slug}.zip"),
        size=0,
        components=[Component(stem=slug, names=[f"{slug}.pak"], assets=assets)],
    )


def test_a_named_mod_teaches_the_character_it_changes():
    known = mod("Doctor Strange", [STRANGE], "known")

    Catalog._name_from_containers([known])

    assert heroes.hero_for_character("1018") == "Doctor Strange"


def test_an_unnamed_mod_takes_the_hero_the_id_belongs_to():
    known = mod("Doctor Strange", [STRANGE], "known")
    nameless = mod("Unknown", [STRANGE], "pants")

    named = Catalog._name_from_containers([known, nameless])

    assert named == 1
    assert nameless.hero == "Doctor Strange"


def test_a_pak_touching_two_characters_names_nothing():
    # Which of the two is the mod "for"? The paths do not say, and guessing
    # would file it under the wrong hero and warn about the wrong things.
    known = mod("Doctor Strange", [STRANGE], "known")
    ambiguous = mod("Unknown", BOTH, "both")

    Catalog._name_from_containers([known, ambiguous])

    assert ambiguous.hero == "Unknown"


def test_an_unrecognised_character_is_named_by_its_id():
    # The game adds a hero every season, so the table is always behind. The id
    # still groups the mods together and tells the user what to add.
    nameless = mod("Unknown", [MAGNETO], "mystery")

    Catalog._name_from_containers([nameless])

    assert nameless.hero == "Character 1037"
    assert "1037" in nameless.note


def test_what_is_learned_survives_a_restart(tmp_path):
    Catalog._name_from_containers([mod("Magneto", [MAGNETO], "known")])
    heroes.forget_characters()

    assert heroes.hero_for_character("1037") == "Magneto"


def test_the_first_confident_answer_wins():
    # A disagreement is far more likely to be a mis-parsed file name than a
    # character changing identity, so an id already known is not overwritten.
    Catalog._name_from_containers([mod("Magneto", [MAGNETO], "first")])
    Catalog._name_from_containers([mod("Storm", [MAGNETO], "second")])

    assert heroes.hero_for_character("1037") == "Magneto"


def test_a_mod_with_no_character_assets_is_left_alone():
    nameless = mod("Unknown", ["/marvel/content/ui/icons/t_thing.uasset"], "ui")

    Catalog._name_from_containers([nameless])

    assert nameless.hero == "Unknown"


# -- costume names -------------------------------------------------------


@pytest.fixture
def costume_store(tmp_path, monkeypatch):
    monkeypatch.setattr(heroes, "COSTUMES_FILE", tmp_path / "costumes.json")
    monkeypatch.setattr(heroes, "COSTUME_OVERLAY_FILE", tmp_path / "costumes.toml")
    monkeypatch.setattr(heroes, "DATA_DIR", tmp_path)
    heroes.forget_costumes()
    yield tmp_path
    heroes.forget_costumes()


def test_a_costume_several_mods_agree_on_is_named(costume_store):
    heroes.learn_costumes({"1044800": ["BladeKnight", "BladeKnight", "Thong"]})

    assert heroes.costume_name("1044800") == "BladeKnight"


def test_one_mod_alone_does_not_name_a_costume(costume_store):
    # File names are wrong often enough that a single voice must not decide.
    heroes.learn_costumes({"1044800": ["Skimpy outfit"]})

    assert heroes.costume_name("1044800") == "1044800"


def test_the_default_costume_needs_no_vote(costume_store):
    # Its id always ends 001, so the game already told us.
    heroes.learn_costumes({"1026001": []})

    assert heroes.costume_name("1026001") == "Default"


def test_words_describing_a_change_are_not_costume_names(costume_store):
    heroes.learn_costumes({"1044800": ["Oily", "Oily", "Thong", "Thong"]})

    assert heroes.costume_name("1044800") == "1044800"


def test_what_the_user_wrote_wins(costume_store):
    (costume_store / "costumes.toml").write_text(
        '[costumes]\n"1044800" = "Blade Knight"\n'
    )
    heroes.forget_costumes()
    heroes.learn_costumes({"1044800": ["BladeKnight", "BladeKnight"]})

    assert heroes.costume_name("1044800") == "Blade Knight"


def test_a_learned_name_survives_a_restart(costume_store):
    heroes.learn_costumes({"1021501": ["Freefall", "Freefall"]})
    heroes.forget_costumes()

    assert heroes.costume_name("1021501") == "Freefall"


def test_an_unnamed_costume_reports_its_id(costume_store):
    assert heroes.costume_name("9999999") == "9999999"
