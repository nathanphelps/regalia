"""Which pak sets of one archive may run together, and which the installer links.

These rules replace the old assumption that an archive is one pak set. The cases
here are taken from real mod pages: a body-size ladder where every rung claims
the same mesh, and a physics add-on that claims nothing anyone else does.
"""

from __future__ import annotations

from pathlib import Path

from regalia import components, installer
from regalia.model import Component, Mod, State

MESH = "/marvel/content/marvel/characters/1053/1053301/meshes/sk_1053_1053301.uasset"
PHYSICS = "/marvel/content/marvel/characters/1053/1053301/post_1053301_physics.uasset"


def part(stem: str, folder: str = "", assets: list[str] | None = None) -> Component:
    return Component(
        stem=stem,
        folder=folder,
        names=[f"{stem}.pak", f"{stem}.utoc", f"{stem}.ucas"],
        assets=assets if assets is not None else [MESH],
        enabled=False,
    )


def make_mod(parts: list[Component]) -> Mod:
    return Mod(
        slug="test",
        hero="Emma Frost",
        variant="Queen",
        version=None,
        nexus_id=None,
        source=Path("/tmp/test.zip"),
        size=0,
        components=parts,
    )


def test_two_sets_writing_one_asset_may_not_both_run():
    small, large = part("small"), part("large")
    assert components.overlap(small, large) == {MESH}


def test_a_set_writing_nothing_in_common_runs_alongside():
    body, physics = part("body"), part("physics", assets=[PHYSICS])
    assert components.overlap(body, physics) == set()


def test_a_size_ladder_becomes_one_group_and_the_add_on_stands_alone():
    parts = [part(name) for name in ("M", "L", "XL")]
    parts.append(part("physics", assets=[PHYSICS]))

    grouped = components.groups(parts)
    sizes = [group for group in grouped if len(group) > 1]

    assert len(grouped) == 2
    assert len(sizes) == 1 and len(sizes[0]) == 3
    assert [item.stem for group in grouped if len(group) == 1 for item in group] == [
        "physics"
    ]


def test_the_default_selection_runs_one_of_each_group():
    parts = [part(name) for name in ("M", "L", "XL")] + [
        part("physics", assets=[PHYSICS])
    ]
    components.choose_default(parts)

    enabled = [item.stem for item in parts if item.enabled]
    assert len(enabled) == 2
    assert "physics" in enabled


def test_enabling_a_set_switches_off_what_it_would_overwrite():
    small, large = part("small"), part("large")
    small.enabled = True
    parts = [small, large]

    displaced = components.enable(large, parts)

    assert displaced == [small]
    assert large.enabled and not small.enabled


def test_an_unreadable_container_falls_back_to_the_folder():
    # Two sets in one folder are the author's alternatives far more often than
    # they are add-ons, and installing both is the failure worth avoiding.
    left = part("one", folder="Options", assets=[])
    right = part("two", folder="Options", assets=[])

    assert components.overlap(left, right)
    assert not components.is_certain(left, right)


def test_unreadable_containers_in_different_folders_are_left_alone():
    left = part("one", folder="Body", assets=[])
    right = part("two", folder="Physics", assets=[])

    assert components.overlap(left, right) == set()


def test_only_the_chosen_sets_are_linked(tmp_path, monkeypatch):
    store = tmp_path / "store"
    mods_dir = tmp_path / "~mods"
    monkeypatch.setattr(installer, "STORE_DIR", store)

    mod = make_mod([part("M"), part("L"), part("physics", assets=[PHYSICS])])
    components.choose_default(mod.components)
    for item in mod.components:
        folder = store / mod.slug / item.folder
        folder.mkdir(parents=True, exist_ok=True)
        for name in item.names:
            (folder / name).write_bytes(b"")

    installer.link(mod, mods_dir)
    linked = sorted(path.name for path in mods_dir.iterdir())

    # One body option and the add-on: six files, not nine.
    assert len(linked) == 6
    assert "physics.pak" in linked
    assert not ("M.pak" in linked and "L.pak" in linked)


def test_a_mod_with_nothing_enabled_claims_no_names():
    mod = make_mod([part("M"), part("L")])
    assert mod.files == []
    assert len(mod.all_files) == 6


def test_unlinking_removes_names_left_by_an_earlier_choice(tmp_path, monkeypatch):
    store = tmp_path / "store"
    mods_dir = tmp_path / "~mods"
    mods_dir.mkdir()
    monkeypatch.setattr(installer, "STORE_DIR", store)

    mod = make_mod([part("M"), part("L")])
    for item in mod.components:
        (store / mod.slug).mkdir(parents=True, exist_ok=True)
        for name in item.names:
            (store / mod.slug / name).write_bytes(b"")
            (mods_dir / name).symlink_to(store / mod.slug / name)
    mod.state = State.INSTALLED

    installer.unlink(mod, mods_dir)

    assert list(mods_dir.iterdir()) == []


def test_sibling_folders_under_one_parent_read_as_alternatives():
    # A size ladder is "Default/L", "Default/M". Before extraction nothing can
    # be read, and comparing the folders whole would call these unrelated and
    # install both.
    left = part("L", folder="Mod/Default/L", assets=[])
    right = part("M", folder="Mod/Default/M", assets=[])

    assert components.overlap(left, right)


def test_a_guess_made_before_extraction_is_narrowed_once_assets_are_readable():
    # This is the shape the real bug took: the listing from the archive has no
    # assets, the folder guess switched every part on, and the carried-over
    # selection was then trusted rather than re-checked.
    listed = [part(name, folder=f"Mod/{name}", assets=[]) for name in ("L", "M", "XL")]
    for item in listed:
        item.enabled = True

    extracted = [part(name, folder=f"Mod/{name}") for name in ("L", "M", "XL")]
    extracted.append(part("physics", folder="Mod/_Physics", assets=[PHYSICS]))
    for item in extracted:
        item.enabled = True

    installer._carry_choices(listed, extracted)

    enabled = sorted(item.stem for item in extracted if item.enabled)
    assert enabled == ["L", "physics"]


def test_resolve_reports_what_it_switched_off():
    parts = [part("M"), part("L"), part("physics", assets=[PHYSICS])]
    for item in parts:
        item.enabled = True

    dropped = components.resolve(parts)

    assert [item.stem for item in dropped] == ["L"]
    assert sorted(item.stem for item in parts if item.enabled) == ["M", "physics"]


def test_a_selection_survives_a_re_extract():
    previous = [part("M"), part("L")]
    previous[1].enabled = True
    found = [part("M"), part("L"), part("XL")]

    installer._carry_choices(previous, found)

    assert [item.stem for item in found if item.enabled] == ["L"]


def test_a_mod_whose_name_another_took_over_is_not_called_installed(
    tmp_path, monkeypatch
):
    """Two archives can ship a container with the same stem.

    Only one of them owns the link. Asking whether *a* link exists at that name
    called both installed, so the loser looked deployed while none of its files
    were reachable — and Repair never touched it, because nothing looked wrong.
    """
    store = tmp_path / "store"
    mods_dir = tmp_path / "~mods"
    mods_dir.mkdir()
    monkeypatch.setattr(installer, "STORE_DIR", store)

    winner = make_mod([part("Shared", assets=[MESH])])
    winner.slug = "winner"
    loser = make_mod([part("Shared", assets=[PHYSICS])])
    loser.slug = "loser"
    for mod in (winner, loser):
        (store / mod.slug).mkdir(parents=True)
        for name in mod.components[0].names:
            (store / mod.slug / name).write_bytes(b"")
        mod.components[0].enabled = True

    installer.link(loser, mods_dir)
    installer.link(winner, mods_dir, overwrite=True)

    assert installer.linked_names(winner, mods_dir) == set(winner.files)
    assert installer.linked_names(loser, mods_dir) == set()


def test_unlinking_leaves_a_name_another_mod_took_over(tmp_path, monkeypatch):
    store = tmp_path / "store"
    mods_dir = tmp_path / "~mods"
    mods_dir.mkdir()
    monkeypatch.setattr(installer, "STORE_DIR", store)

    winner = make_mod([part("Shared", assets=[MESH])])
    winner.slug = "winner"
    loser = make_mod([part("Shared", assets=[PHYSICS])])
    loser.slug = "loser"
    for mod in (winner, loser):
        (store / mod.slug).mkdir(parents=True)
        for name in mod.components[0].names:
            (store / mod.slug / name).write_bytes(b"")
        mod.components[0].enabled = True

    installer.link(loser, mods_dir)
    installer.link(winner, mods_dir, overwrite=True)
    installer.unlink(loser, mods_dir)

    # The winner keeps its links: removing them would uninstall it silently.
    assert installer.linked_names(winner, mods_dir) == set(winner.files)
