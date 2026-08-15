"""Installing the signature bypass.

The archives come from Windows, where file names are case-insensitive, so their
contents arrive spelled however the author's tooling wrote them. Everything that
looks for the loader or a plugin has to allow for that, or the tool detects an
archive as a patch and then refuses to install it.
"""

from __future__ import annotations

import zipfile

import pytest

from regalia import archive, patch
from regalia.paths import GamePaths


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "game"
    paths = GamePaths(root)
    paths.binaries.mkdir(parents=True)
    return paths


def make_archive(path, names: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as handle:
        for name, data in names.items():
            handle.writestr(name, data)
    return path


def test_the_loader_and_plugin_are_placed(tmp_path, game):
    source = make_archive(
        tmp_path / "patch.zip",
        {"dsound.dll": b"loader", "plugins/bypass.asi": b"plugin"},
    )

    placed = patch.install(game, source, tmp_path / "staging")

    assert "dsound.dll" in placed
    assert (game.binaries / "dsound.dll").is_file()
    assert (game.binaries / "plugins" / "bypass.asi").is_file()


def test_an_archive_written_in_another_case_still_installs(tmp_path, game):
    # This one used to fail: the archive was recognised as a patch, because
    # detection lowercases, and then rejected by the installer, which did not.
    source = make_archive(
        tmp_path / "patch.zip",
        {"DSOUND.DLL": b"loader", "Plugins/Bypass.ASI": b"plugin"},
    )

    placed = patch.install(game, source, tmp_path / "staging")

    assert (game.binaries / "dsound.dll").is_file()
    assert "plugins/Bypass.ASI" in placed


def test_such_an_archive_is_also_reported_as_installed(tmp_path, game):
    source = make_archive(
        tmp_path / "patch.zip",
        {"DSOUND.DLL": b"loader", "Plugins/Bypass.ASI": b"plugin"},
    )
    patch.install(game, source, tmp_path / "staging")

    assert patch.status(game).plugin_installed
    assert patch.status(game).loader_installed


def test_the_loader_is_written_under_the_name_wine_looks_up(tmp_path, game):
    source = make_archive(tmp_path / "patch.zip", {"DSOUND.DLL": b"loader"})

    patch.install(game, source, tmp_path / "staging")

    assert [p.name for p in game.binaries.iterdir() if p.is_file()] == ["dsound.dll"]


def test_an_archive_with_neither_is_refused(tmp_path, game):
    source = make_archive(tmp_path / "patch.zip", {"readme.txt": b"nothing"})

    with pytest.raises(RuntimeError, match="no dsound.dll"):
        patch.install(game, source, tmp_path / "staging")


def test_detection_and_installation_agree_about_what_is_a_patch(tmp_path):
    source = make_archive(
        tmp_path / "patch.zip",
        {"DSOUND.DLL": b"loader", "Plugins/Bypass.ASI": b"plugin"},
    )

    assert archive.looks_like_patch(archive.list_entries(source))


def test_uninstall_removes_plugins_whatever_their_case(tmp_path, game):
    source = make_archive(
        tmp_path / "patch.zip",
        {"dsound.dll": b"loader", "plugins/Bypass.ASI": b"plugin"},
    )
    patch.install(game, source, tmp_path / "staging")

    removed = patch.uninstall(game)

    assert "dsound.dll" in removed
    assert not patch.status(game).plugin_installed
