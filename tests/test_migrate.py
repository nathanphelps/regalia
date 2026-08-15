"""Carrying an installation over from the old name.

The store holds the extracted files and the game folder holds absolute symlinks
into it. Renaming the store without repointing those links would leave every
installed mod reading as broken.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from regalia import migrate


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """An old install: a store with two files, linked into a game folder."""
    old_store = tmp_path / "old/store"
    new_store = tmp_path / "new/store"
    mods = tmp_path / "game/~mods"
    for path in (old_store, new_store, mods):
        path.mkdir(parents=True)

    monkeypatch.setattr(migrate, "STORE_DIR", new_store)
    monkeypatch.setattr(migrate, "legacy_data", lambda: tmp_path / "old")

    for name in ("Loki_P.pak", "Loki_P.utoc"):
        (old_store / "loki" / name).parent.mkdir(exist_ok=True)
        (old_store / "loki" / name).write_text("x")
        (new_store / "loki" / name).parent.mkdir(exist_ok=True)
        (new_store / "loki" / name).write_text("x")
        (mods / name).symlink_to(old_store / "loki" / name)

    return mods, old_store, new_store


def test_links_are_repointed_at_the_new_store(machine):
    mods, _, new_store = machine
    migrate.relink_store(mods)

    for link in mods.iterdir():
        assert Path(os.readlink(link)).is_relative_to(new_store)
        assert link.resolve().is_file()


def test_the_relative_path_inside_the_store_survives(machine):
    mods, _, new_store = machine
    migrate.relink_store(mods)
    assert (mods / "Loki_P.pak").resolve() == new_store / "loki/Loki_P.pak"


def test_the_step_is_reported(machine):
    mods, _, _ = machine
    steps = migrate.relink_store(mods)
    assert any("2 symlink" in step for step in steps)


def test_a_link_outside_the_old_store_is_left_alone(machine, tmp_path):
    mods, _, _ = machine
    other = tmp_path / "elsewhere/other.pak"
    other.parent.mkdir()
    other.write_text("x")
    (mods / "other.pak").symlink_to(other)

    migrate.relink_store(mods)
    assert Path(os.readlink(mods / "other.pak")) == other


def test_a_real_file_is_not_touched(machine):
    mods, _, _ = machine
    plain = mods / "plain.pak"
    plain.write_text("x")

    migrate.relink_store(mods)
    assert plain.is_file() and not plain.is_symlink()


def test_running_twice_changes_nothing(machine):
    mods, _, _ = machine
    migrate.relink_store(mods)
    first = {link.name: os.readlink(link) for link in mods.iterdir()}

    assert migrate.relink_store(mods) == []
    assert {link.name: os.readlink(link) for link in mods.iterdir()} == first


def test_a_missing_mods_folder_is_not_an_error(tmp_path):
    assert migrate.relink_store(tmp_path / "absent") == []
