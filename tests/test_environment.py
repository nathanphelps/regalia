"""Environment detection over fake machines.

These are the checks that cannot be made by hand: the author runs one
distribution with one Steam flavour, and the code has to serve five.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from regalia.environment import (
    FLATPAK_ID,
    SteamFlavor,
    download_dir,
    find_steam_installs,
    flavor_for,
    xdg_cache_home,
    xdg_config_home,
    xdg_data_home,
)

FLAVOUR_ROOTS = {
    SteamFlavor.NATIVE: ".local/share/Steam",
    SteamFlavor.DEB: ".steam/debian-installation",
    SteamFlavor.FLATPAK: f".var/app/{FLATPAK_ID}/data/Steam",
    SteamFlavor.SNAP: "snap/steam/common/.local/share/Steam",
}


def make_steam(home: Path, relative: str) -> Path:
    """Build just enough of a Steam tree to be recognised."""
    root = home / relative
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps/libraryfolders.vdf").write_text('"libraryfolders"\n{\n}\n')
    return root


# -- base directories ----------------------------------------------------


def test_xdg_defaults_when_unset(tmp_path):
    assert xdg_config_home(tmp_path, {}) == tmp_path / ".config"
    assert xdg_data_home(tmp_path, {}) == tmp_path / ".local/share"
    assert xdg_cache_home(tmp_path, {}) == tmp_path / ".cache"


def test_xdg_honours_an_absolute_override(tmp_path):
    env = {"XDG_CONFIG_HOME": "/somewhere/conf"}
    assert xdg_config_home(tmp_path, env) == Path("/somewhere/conf")


def test_xdg_ignores_a_relative_override(tmp_path):
    """The specification says a relative value must be ignored."""
    env = {"XDG_DATA_HOME": "relative/share"}
    assert xdg_data_home(tmp_path, env) == tmp_path / ".local/share"


# -- the downloads folder ------------------------------------------------


def test_download_dir_falls_back_to_downloads(tmp_path):
    assert download_dir(tmp_path, {}) == tmp_path / "Downloads"


def test_download_dir_reads_the_environment_first(tmp_path):
    env = {"XDG_DOWNLOAD_DIR": "$HOME/Telechargements"}
    assert download_dir(tmp_path, env) == tmp_path / "Telechargements"


def test_download_dir_reads_user_dirs_for_a_localised_desktop(tmp_path):
    """A French desktop names the folder Téléchargements, not Downloads."""
    config = tmp_path / ".config"
    config.mkdir()
    (config / "user-dirs.dirs").write_text(
        "# generated\n"
        'XDG_DESKTOP_DIR="$HOME/Bureau"\n'
        'XDG_DOWNLOAD_DIR="$HOME/Téléchargements"\n'
    )
    assert download_dir(tmp_path, {}) == tmp_path / "Téléchargements"


def test_download_dir_ignores_an_empty_user_dirs_entry(tmp_path):
    config = tmp_path / ".config"
    config.mkdir()
    (config / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR=""\n')
    assert download_dir(tmp_path, {}) == tmp_path / "Downloads"


# -- finding Steam -------------------------------------------------------


@pytest.mark.parametrize("flavor", list(SteamFlavor))
def test_each_flavour_is_found_and_labelled(tmp_path, flavor):
    root = make_steam(tmp_path, FLAVOUR_ROOTS[flavor])
    found = find_steam_installs(None, tmp_path, {})
    assert [(i.root, i.flavor) for i in found] == [(root, flavor)]


def test_nothing_is_found_on_a_bare_machine(tmp_path):
    assert find_steam_installs(None, tmp_path, {}) == []


def test_a_directory_without_libraryfolders_is_not_steam(tmp_path):
    (tmp_path / ".local/share/Steam/steamapps").mkdir(parents=True)
    assert find_steam_installs(None, tmp_path, {}) == []


def test_a_symlinked_root_is_not_reported_twice(tmp_path):
    """~/.steam/steam usually points at the native root."""
    root = make_steam(tmp_path, ".local/share/Steam")
    link = tmp_path / ".steam"
    link.mkdir()
    (link / "steam").symlink_to(root)

    found = find_steam_installs(None, tmp_path, {})
    assert [i.root for i in found] == [root]


def test_the_native_root_wins_over_flatpak(tmp_path):
    """Both can exist. The native one is listed first, so it is chosen first."""
    native = make_steam(tmp_path, ".local/share/Steam")
    flatpak = make_steam(tmp_path, FLAVOUR_ROOTS[SteamFlavor.FLATPAK])

    found = find_steam_installs(None, tmp_path, {})
    assert [i.root for i in found] == [native, flatpak]
    assert found[1].flavor is SteamFlavor.FLATPAK


def test_xdg_data_home_moves_the_native_root(tmp_path):
    elsewhere = tmp_path / "data"
    root = elsewhere / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps/libraryfolders.vdf").write_text("{}")

    found = find_steam_installs(None, tmp_path, {"XDG_DATA_HOME": str(elsewhere)})
    assert [i.root for i in found] == [root]


def test_an_override_is_tried_first(tmp_path):
    make_steam(tmp_path, ".local/share/Steam")
    chosen = make_steam(tmp_path, "elsewhere/Steam")

    found = find_steam_installs(chosen, tmp_path, {})
    assert found[0].root == chosen


def test_an_override_keeps_its_flavour(tmp_path):
    chosen = make_steam(tmp_path, FLAVOUR_ROOTS[SteamFlavor.FLATPAK])
    found = find_steam_installs(chosen, tmp_path, {})
    assert found[0].flavor is SteamFlavor.FLATPAK


def test_a_bad_override_does_not_hide_the_real_one(tmp_path):
    real = make_steam(tmp_path, ".local/share/Steam")
    found = find_steam_installs(tmp_path / "nowhere", tmp_path, {})
    assert [i.root for i in found] == [real]


# -- driving the client --------------------------------------------------


def test_flavour_is_guessed_from_a_typed_path():
    assert flavor_for(Path(f"/home/x/.var/app/{FLATPAK_ID}/data/Steam")) is (
        SteamFlavor.FLATPAK
    )
    assert flavor_for(Path("/home/x/snap/steam/common/x")) is SteamFlavor.SNAP
    assert flavor_for(Path("/home/x/.steam/debian-installation")) is SteamFlavor.DEB
    assert flavor_for(Path("/home/x/.local/share/Steam")) is SteamFlavor.NATIVE


def test_flatpak_is_stopped_through_flatpak(tmp_path, monkeypatch):
    monkeypatch.setattr("regalia.environment.shutil.which", lambda name: f"/bin/{name}")
    make_steam(tmp_path, FLAVOUR_ROOTS[SteamFlavor.FLATPAK])
    install = find_steam_installs(None, tmp_path, {})[0]

    assert install.shutdown_command() == [
        "flatpak",
        "run",
        FLATPAK_ID,
        "-shutdown",
    ]
    assert install.start_command() == ["flatpak", "run", FLATPAK_ID]


def test_snap_is_stopped_through_snap(tmp_path, monkeypatch):
    monkeypatch.setattr("regalia.environment.shutil.which", lambda name: f"/bin/{name}")
    make_steam(tmp_path, FLAVOUR_ROOTS[SteamFlavor.SNAP])
    install = find_steam_installs(None, tmp_path, {})[0]
    assert install.shutdown_command() == ["snap", "run", "steam", "-shutdown"]


def test_native_is_stopped_through_the_steam_command(tmp_path, monkeypatch):
    monkeypatch.setattr("regalia.environment.shutil.which", lambda name: f"/bin/{name}")
    make_steam(tmp_path, ".local/share/Steam")
    install = find_steam_installs(None, tmp_path, {})[0]
    assert install.shutdown_command() == ["steam", "-shutdown"]


def test_no_command_is_offered_when_the_launcher_is_absent(tmp_path, monkeypatch):
    """The caller must ask the user to close Steam instead of failing."""
    monkeypatch.setattr("regalia.environment.shutil.which", lambda name: None)
    make_steam(tmp_path, FLAVOUR_ROOTS[SteamFlavor.FLATPAK])
    install = find_steam_installs(None, tmp_path, {})[0]
    assert install.shutdown_command() is None
    assert install.start_command() is None


def test_flatpak_gets_an_extra_process_probe(tmp_path):
    make_steam(tmp_path, FLAVOUR_ROOTS[SteamFlavor.FLATPAK])
    install = find_steam_installs(None, tmp_path, {})[0]
    probes = install.process_probes()
    assert ["pgrep", "-x", "steam"] in probes
    assert ["pgrep", "-f", FLATPAK_ID] in probes
