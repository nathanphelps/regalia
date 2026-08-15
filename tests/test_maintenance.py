"""Resetting, and what counts as the tool's own to remove.

The ownership test matters more than it looks. A user whose catalog is gone —
deleted by hand, or cleared during a tidy-up — still has a game folder full of
links, and the catalog can no longer name any of them. If the catalog were the
only test, a reset would report nothing to do and the links would be stuck.
"""

from __future__ import annotations

import pytest

from regalia import maintenance


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = tmp_path / "store"
    (store / "a-mod").mkdir(parents=True)
    monkeypatch.setattr(maintenance, "STORE_DIR", store)
    return store


def test_a_link_into_our_store_is_ours(tmp_path, store):
    real = store / "a-mod" / "Mod_P.pak"
    real.write_bytes(b"")
    link = tmp_path / "Mod_P.pak"
    link.symlink_to(real)

    assert maintenance.owns_link(link)


def test_a_link_whose_target_was_deleted_is_still_ours(tmp_path, store):
    # This is the state a tidy-up leaves behind, and the one a reset has to
    # clear. `readlink` still answers, so the link is still recognisable.
    link = tmp_path / "Mod_P.pak"
    link.symlink_to(store / "a-mod" / "gone.pak")

    assert not link.exists()
    assert maintenance.owns_link(link)


def test_a_link_somewhere_else_is_left_alone(tmp_path, store):
    other = tmp_path / "elsewhere.pak"
    other.write_bytes(b"")
    link = tmp_path / "Mod_P.pak"
    link.symlink_to(other)

    assert not maintenance.owns_link(link)


def test_a_real_file_is_never_ours(tmp_path, store):
    plain = tmp_path / "someone-elses.pak"
    plain.write_bytes(b"")

    assert not maintenance.owns_link(plain)


def test_links_are_found_without_help_from_the_catalog(tmp_path, store):
    mods = tmp_path / "~mods"
    mods.mkdir()
    (mods / "Mine_P.pak").symlink_to(store / "a-mod" / "Mine_P.pak")
    (mods / "Theirs_P.pak").symlink_to(tmp_path / "somewhere-else.pak")

    todo = maintenance.plan(["links"], mods, claimed=set())

    assert [item.path.name for item in todo.items] == ["Mine_P.pak"]


def test_the_catalog_can_still_claim_a_link_it_knows(tmp_path, store):
    mods = tmp_path / "~mods"
    mods.mkdir()
    (mods / "Named_P.pak").symlink_to(tmp_path / "outside.pak")

    todo = maintenance.plan(["links"], mods, claimed={"Named_P.pak"})

    assert [item.path.name for item in todo.items] == ["Named_P.pak"]


def test_an_unknown_scope_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown scope"):
        maintenance.plan(["nonsense"], None, set())


def test_a_sweep_never_reaches_the_library():
    # Re-downloading a large collection is the one cost a reset must not impose
    # by accident, so "all" has to leave the library out.
    assert "library" in maintenance.DESTRUCTIVE
    assert "library" not in [
        s for s in maintenance.SCOPES if s not in maintenance.DESTRUCTIVE
    ]


def test_running_a_plan_removes_only_what_it_listed(tmp_path, store):
    mods = tmp_path / "~mods"
    mods.mkdir()
    (mods / "Mine_P.pak").symlink_to(store / "a-mod" / "Mine_P.pak")
    keep = mods / "Theirs_P.pak"
    keep.symlink_to(tmp_path / "somewhere-else.pak")

    maintenance.run(maintenance.plan(["links"], mods, claimed=set()))

    assert [path.name for path in mods.iterdir()] == ["Theirs_P.pak"]


def test_bytes_are_reported_in_a_unit_a_person_reads():
    assert maintenance.human(512) == "512 B"
    assert maintenance.human(2048) == "2.0 KB"
    assert maintenance.human(5 * 1024**3) == "5.0 GB"
