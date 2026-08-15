"""Config mods, which change settings instead of shipping files.

This is the one place the tool writes into a file the game owns and rewrites,
beside settings the user chose themselves. Everything here is about not damaging
those: touch only the named keys, remember what stood there, and put it back.
"""

from __future__ import annotations

import pytest

from regalia import gameconfig
from regalia.gameconfig import Setting

EXISTING = """[SystemSettings]
r.MotionBlurQuality=0

[/Script/Engine.RendererSettings]
r.Shadow.MaxCSMResolution=1024
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(gameconfig, "BACKUP_DIR", tmp_path / "backups")
    path = tmp_path / "Engine.ini"
    path.write_text(EXISTING)
    return path


def test_settings_are_read_out_of_a_mod_file():
    found = gameconfig.parse(
        "; a comment\n[SystemSettings]\nr.postprocessing.EnableHeroOutline=0\n"
    )

    assert len(found) == 1
    assert found[0].section == "SystemSettings"
    assert found[0].key == "r.postprocessing.EnableHeroOutline"
    assert found[0].value == "0"


def test_a_key_outside_any_section_is_ignored():
    # Unreal ignores it too, and guessing a section would put the setting
    # somewhere the author never asked for.
    assert gameconfig.parse("stray=1\n[A]\nreal=2\n") == [Setting("A", "real", "2")]


def test_a_new_key_joins_the_section_it_belongs_to(config):
    gameconfig.apply([Setting("SystemSettings", "r.Fog", "0")], config)

    text = config.read_text()
    assert "[SystemSettings]\nr.MotionBlurQuality=0\nr.Fog=0" in text
    # The blank line goes on separating the sections rather than landing inside
    # one of them.
    assert "\n\n[/Script/Engine.RendererSettings]" in text


def test_a_section_that_does_not_exist_is_created(config):
    gameconfig.apply([Setting("NewOne", "key", "1")], config)

    assert "[NewOne]\nkey=1" in config.read_text()


def test_settings_the_user_already_had_are_left_alone(config):
    gameconfig.apply([Setting("SystemSettings", "r.Fog", "0")], config)

    text = config.read_text()
    assert "r.MotionBlurQuality=0" in text
    assert "r.Shadow.MaxCSMResolution=1024" in text


def test_uninstalling_removes_only_what_the_mod_added(config):
    settings = [Setting("SystemSettings", "r.Fog", "0")]
    gameconfig.apply(settings, config)

    gameconfig.revoke(settings, config)

    assert config.read_text() == EXISTING


def test_a_value_the_mod_replaced_is_put_back(config):
    # The mod overwrote a setting the user had chosen. Removing the mod must
    # restore their value rather than delete the line.
    settings = [Setting("SystemSettings", "r.MotionBlurQuality", "3")]
    gameconfig.apply(settings, config)
    assert settings[0].previous == "0"
    assert "r.MotionBlurQuality=3" in config.read_text()

    gameconfig.revoke(settings, config)

    assert "r.MotionBlurQuality=0" in config.read_text()


def test_a_setting_changed_since_install_is_not_reverted(config):
    # Someone edited it after the mod went in. That is a later decision than
    # the mod, and removing the mod does not entitle it to undo one.
    settings = [Setting("SystemSettings", "r.Fog", "0")]
    gameconfig.apply(settings, config)
    config.write_text(config.read_text().replace("r.Fog=0", "r.Fog=2"))

    gameconfig.revoke(settings, config)

    assert "r.Fog=2" in config.read_text()


def test_whether_a_mod_is_in_force_is_read_from_the_file(config):
    settings = [Setting("SystemSettings", "r.Fog", "0")]

    assert not gameconfig.is_applied(settings, config)
    gameconfig.apply(settings, config)
    assert gameconfig.is_applied(settings, config)


def test_a_missing_settings_file_is_created(tmp_path, monkeypatch):
    monkeypatch.setattr(gameconfig, "BACKUP_DIR", tmp_path / "backups")
    # Unreal reads this file when it is there and does without it when it is
    # not, so a fresh installation simply has none.
    path = tmp_path / "deep" / "Engine.ini"

    gameconfig.apply([Setting("SystemSettings", "r.Fog", "0")], path)

    assert path.read_text() == "[SystemSettings]\nr.Fog=0\n"


def test_the_file_is_copied_aside_before_it_is_changed(config, tmp_path):
    gameconfig.apply([Setting("SystemSettings", "r.Fog", "0")], config)

    backups = list((tmp_path / "backups").glob("Engine-*.ini"))
    assert len(backups) == 1
    assert backups[0].read_text() == EXISTING


def test_case_does_not_hide_an_existing_key(config):
    # Unreal treats these names case-insensitively, so matching exactly would
    # add a second copy of a key that is already there.
    gameconfig.apply([Setting("systemsettings", "R.MOTIONBLURQUALITY", "5")], config)

    assert (
        config.read_text().count("MotionBlur") + config.read_text().count("MOTIONBLUR")
        == 1
    )


def test_a_byte_that_is_not_utf8_survives(config):
    config.write_bytes(b"[SystemSettings]\n; Caf\xe9\nr.MotionBlurQuality=0\n")

    gameconfig.apply([Setting("SystemSettings", "r.Fog", "0")], config)

    assert b"\xe9" in config.read_bytes()
