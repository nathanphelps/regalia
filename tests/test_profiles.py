"""Saving a deployment and switching back to it.

The part that needs covering is that a profile remembers *which parts* of a mod
ran, not only that the mod ran. A twenty-four part archive has one body size
chosen out of it, and a profile that forgets which one silently changes the
result on the way back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from regalia import installer, profiles
from regalia.model import Component, Mod, State

MESH = "/marvel/characters/1053/1053301/meshes/sk.uasset"
OTHER = "/marvel/characters/1046/1046001/meshes/sk.uasset"


def part(stem: str, folder: str = "", assets=None, enabled: bool = False) -> Component:
    return Component(
        stem=stem,
        folder=folder,
        names=[f"{stem}.pak", f"{stem}.utoc"],
        assets=[MESH] if assets is None else assets,
        enabled=enabled,
    )


def make(slug: str, parts: list[Component], state: State = State.AVAILABLE) -> Mod:
    return Mod(
        slug=slug,
        hero="Emma Frost",
        variant=slug,
        version=None,
        nexus_id=None,
        source=Path(f"/tmp/{slug}.zip"),
        size=0,
        components=parts,
        state=state,
    )


@pytest.fixture
def deployed(tmp_path, monkeypatch):
    """Two mods on disk, one of them with a choice of parts."""
    store = tmp_path / "store"
    mods_dir = tmp_path / "~mods"
    mods_dir.mkdir()
    monkeypatch.setattr(installer, "STORE_DIR", store)

    ladder = make("emma", [part("M"), part("L"), part("physics", assets=[OTHER])])
    plain = make("adam", [part("adam", assets=[OTHER])])
    for mod in (ladder, plain):
        for component in mod.components:
            folder = store / mod.slug / component.folder
            folder.mkdir(parents=True, exist_ok=True)
            for name in component.names:
                (folder / name).write_bytes(b"")
    return ladder, plain, mods_dir


def test_a_profile_records_which_parts_ran(deployed):
    ladder, plain, mods_dir = deployed
    ladder.components[1].enabled = True  # L
    ladder.components[2].enabled = True  # physics
    installer.link(ladder, mods_dir)

    saved = profiles.capture("night", [ladder, plain])

    assert saved.parts == {"emma": ["L", "physics"]}
    assert "adam" not in saved.parts  # never installed


def test_switching_back_restores_the_part_that_was_chosen(deployed):
    ladder, plain, mods_dir = deployed
    ladder.components[1].enabled = True
    installer.link(ladder, mods_dir)
    saved = profiles.capture("night", [ladder, plain])

    # Change the choice, as a user would.
    ladder.components[1].enabled = False
    ladder.components[0].enabled = True  # M
    installer.apply_selection(ladder, mods_dir)
    assert sorted(p.name for p in mods_dir.iterdir()) == ["M.pak", "M.utoc"]

    profiles.apply(saved, [ladder, plain], mods_dir)

    assert sorted(p.name for p in mods_dir.iterdir()) == ["L.pak", "L.utoc"]


def test_a_mod_the_profile_does_not_name_is_unlinked_but_kept(deployed):
    ladder, plain, mods_dir = deployed
    plain.components[0].enabled = True
    installer.link(plain, mods_dir)
    empty = profiles.Profile(name="none", parts={})

    result = profiles.apply(empty, [ladder, plain], mods_dir)

    assert result.unlinked == ["adam"]
    assert list(mods_dir.iterdir()) == []
    # The extracted files stay, so switching back costs no extraction.
    assert (installer.STORE_DIR / "adam" / "adam.pak").is_file()


def test_a_mod_already_matching_is_left_alone(deployed):
    ladder, plain, mods_dir = deployed
    ladder.components[1].enabled = True
    installer.link(ladder, mods_dir)
    saved = profiles.capture("night", [ladder, plain])

    result = profiles.apply(saved, [ladder, plain], mods_dir)

    assert result.unchanged == ["emma"]
    assert result.linked == []


def test_a_profile_naming_a_mod_that_is_gone_says_so(deployed):
    ladder, plain, mods_dir = deployed
    saved = profiles.Profile(name="old", parts={"deleted-mod": ["x"]})

    result = profiles.apply(saved, [ladder, plain], mods_dir)

    assert result.missing == ["deleted-mod"]


def test_a_name_is_tidied_and_an_empty_one_refused():
    assert profiles.clean_name("  raid   night  ") == "raid night"
    with pytest.raises(profiles.ProfileError):
        profiles.clean_name("   ")


def test_saving_the_same_name_twice_replaces_it(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr(profiles, "DATA_DIR", tmp_path)
    store = profiles.ProfileStore()
    store.put(profiles.Profile(name="Night", parts={"a": []}))
    store.put(profiles.Profile(name="night", parts={"b": []}))

    assert len(store.profiles) == 1
    assert store.profiles[0].parts == {"b": []}


def test_profiles_round_trip_through_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr(profiles, "DATA_DIR", tmp_path)
    store = profiles.ProfileStore()
    store.put(profiles.Profile(name="night", parts={"emma": ["L", "physics"]}))
    store.save()

    again = profiles.ProfileStore.load()

    assert again.names == ["night"]
    assert again.get("NIGHT").parts == {"emma": ["L", "physics"]}


def test_a_broken_profiles_file_does_not_stop_the_tool(tmp_path, monkeypatch):
    broken = tmp_path / "profiles.json"
    broken.write_text("{not json")
    monkeypatch.setattr(profiles, "PROFILES_FILE", broken)

    assert profiles.ProfileStore.load().profiles == []


def test_removing_a_profile_reports_whether_it_was_there(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES_FILE", tmp_path / "profiles.json")
    store = profiles.ProfileStore([profiles.Profile(name="night")])

    assert store.remove("Night")
    assert not store.remove("night")
