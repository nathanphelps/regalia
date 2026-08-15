"""Carrying a catalog over from the version that linked every pak set.

The old record held one flat list of file names and the old installer linked all
of them. A library that arrives that way has ten body options running at once,
so reading it has to narrow the selection rather than preserve it faithfully.
"""

from __future__ import annotations

from pathlib import Path

from regalia.catalog import Catalog
from regalia.model import Component, Mod

MESH = "/marvel/characters/1053/1053301/meshes/sk.uasset"
PHYSICS = "/marvel/characters/1053/1053301/post_physics.uasset"


def old_record(names: list[str]) -> dict:
    return {
        "slug": "emma",
        "hero": "Emma Frost",
        "variant": "Queen",
        "version": None,
        "nexus_id": "6347",
        "source": "/tmp/emma.zip",
        "size": 10,
        "files": names,
        "state": "installed",
    }


def test_a_flat_file_list_becomes_one_component_per_pak_set():
    mod = Mod.from_json(
        old_record(["A_P.pak", "A_P.ucas", "A_P.utoc", "B_P.pak", "B_P.utoc"])
    )

    assert [item.stem for item in mod.components] == ["A_P", "B_P"]
    assert mod.components[0].names == ["A_P.pak", "A_P.ucas", "A_P.utoc"]
    # Every one is on, because that is what the old installer did on disk.
    assert all(item.enabled for item in mod.components)


def test_a_record_round_trips_through_the_new_format():
    mod = Mod.from_json(old_record(["A_P.pak", "A_P.utoc"]))
    mod.components[0].assets = [MESH]

    again = Mod.from_json(mod.to_json())

    assert again.components[0].assets == [MESH]
    assert again.components[0].stem == "A_P"


def part(stem: str, assets: list[str], enabled: bool = True) -> Component:
    return Component(stem=stem, names=[f"{stem}.pak"], assets=assets, enabled=enabled)


def make_mod(parts: list[Component]) -> Mod:
    return Mod(
        slug="emma",
        hero="Emma Frost",
        variant="Queen",
        version=None,
        nexus_id=None,
        source=Path("/tmp/emma.zip"),
        size=0,
        components=parts,
    )


def test_options_that_overwrite_each_other_are_narrowed_to_one():
    mod = make_mod([part("M", [MESH]), part("L", [MESH]), part("XL", [MESH])])
    found = [part("M", [MESH]), part("L", [MESH]), part("XL", [MESH])]

    note = Catalog._adopt(mod, found)

    assert [item.stem for item in mod.components if item.enabled] == ["M"]
    assert "turned off 2" in note


def test_an_add_on_keeps_running_beside_the_option_that_was_kept():
    parts = [part("M", [MESH]), part("L", [MESH]), part("physics", [PHYSICS])]
    mod = make_mod([part("M", [MESH]), part("L", [MESH]), part("physics", [PHYSICS])])

    Catalog._adopt(mod, parts)

    assert sorted(item.stem for item in mod.components if item.enabled) == [
        "M",
        "physics",
    ]


def test_a_selection_the_user_made_is_left_alone():
    mod = make_mod([part("M", [MESH], enabled=False), part("L", [MESH], enabled=True)])
    found = [part("M", [MESH]), part("L", [MESH])]

    note = Catalog._adopt(mod, found)

    assert [item.stem for item in mod.components if item.enabled] == ["L"]
    assert note == ""


def test_a_first_scan_picks_a_default_rather_than_everything():
    mod = make_mod([])
    found = [part("M", [MESH]), part("L", [MESH]), part("physics", [PHYSICS])]

    Catalog._adopt(mod, found)

    assert sorted(item.stem for item in mod.components if item.enabled) == [
        "M",
        "physics",
    ]
