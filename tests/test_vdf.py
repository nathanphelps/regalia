"""Parsing and rewriting Steam's localconfig.vdf.

A mistake here writes a wrong value into a user's Steam settings, so every
awkward case the real file contains gets a test.
"""

from __future__ import annotations

from regalia.paths import (
    APP_ID,
    _apps_section,
    _launch_options_in,
    escape_vdf,
    unescape_vdf,
)
from regalia.steam import _rewrite, merge_override

# The app id also appears inside binary licence data before the apps section. A
# plain text search finds that copy first and reports nothing, which is the bug
# this fixture exists to keep fixed.
DECOY = f'\t\t\t\t"licenses"\n\t\t\t\t{{\n\t\t\t\t\t"{APP_ID}"\t\t"1"\n\t\t\t\t}}\n'


def config(launch_options: str | None = None, decoy: bool = True) -> str:
    inner = (
        f'\t\t\t\t\t"LaunchOptions"\t\t"{launch_options}"\n'
        if launch_options is not None
        else ""
    )
    return (
        '"UserLocalConfigStore"\n{\n'
        + (DECOY if decoy else "")
        + '\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"apps"\n\t\t\t{\n'
        + f'\t\t\t\t"{APP_ID}"\n\t\t\t\t{{\n'
        + inner
        + '\t\t\t\t\t"LastPlayed"\t\t"1750000000"\n'
        + "\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n"
    )


# -- reading -------------------------------------------------------------


def test_the_apps_section_is_found():
    assert _apps_section(config()) > 0


def test_a_missing_apps_section_starts_at_zero():
    assert _apps_section('"nothing" { }') == 0


def test_launch_options_are_read():
    text = config('WINEDLLOVERRIDES=\\"dsound=n,b\\" %command%')
    assert _launch_options_in(text) == 'WINEDLLOVERRIDES="dsound=n,b" %command%'


def test_an_absent_key_reads_as_empty_not_missing():
    """The block exists but holds no launch options."""
    assert _launch_options_in(config()) == ""


def test_no_block_at_all_reads_as_none():
    assert _launch_options_in('"UserLocalConfigStore"\n{\n}\n') is None


def test_the_licence_decoy_does_not_win():
    """Without the apps-section anchor this returns None."""
    assert _launch_options_in(config("plain", decoy=True)) == "plain"


def test_escaping_round_trips():
    value = 'a "quoted" \\ backslash'
    assert unescape_vdf(escape_vdf(value)) == value


# -- rewriting -----------------------------------------------------------


def test_an_existing_key_is_replaced():
    text = _rewrite(config("old"), "new")
    assert _launch_options_in(text) == "new"


def test_a_missing_key_is_inserted():
    text = _rewrite(config(), "added")
    assert _launch_options_in(text) == "added"


def test_the_rest_of_the_file_survives_a_rewrite():
    text = _rewrite(config("old"), "new")
    assert '"LastPlayed"' in text
    assert '"licenses"' in text


def test_a_quoted_value_is_escaped_on_the_way_in():
    value = 'WINEDLLOVERRIDES="dsound=n,b" %command%'
    text = _rewrite(config(), value)
    assert '\\"dsound=n,b\\"' in text
    assert _launch_options_in(text) == value


def test_rewriting_twice_is_stable():
    once = _rewrite(config("old"), "new")
    twice = _rewrite(once, "new")
    assert once == twice


# -- merging the override ------------------------------------------------


def test_an_empty_value_gets_the_whole_override():
    assert merge_override("") == 'WINEDLLOVERRIDES="dsound=n,b" %command%'


def test_another_dll_is_kept():
    result = merge_override('WINEDLLOVERRIDES="winmm=n,b" %command%')
    assert result == 'WINEDLLOVERRIDES="winmm=n,b;dsound=n,b" %command%'


def test_an_existing_dsound_entry_is_left_alone():
    existing = 'WINEDLLOVERRIDES="dsound=n,b" %command%'
    assert merge_override(existing) == existing


def test_a_differently_written_dsound_entry_is_still_recognised():
    existing = 'WINEDLLOVERRIDES="dsound=b,n" %command%'
    assert merge_override(existing) == existing


def test_other_settings_before_the_placeholder_survive():
    result = merge_override("MANGOHUD=1 %command%")
    assert result == 'MANGOHUD=1 WINEDLLOVERRIDES="dsound=n,b" %command%'


def test_a_value_without_the_placeholder_becomes_game_arguments():
    """Steam passes the whole string to the game when %command% is absent."""
    result = merge_override("-windowed")
    assert result == 'WINEDLLOVERRIDES="dsound=n,b" %command% -windowed'


def test_trailing_arguments_after_the_placeholder_survive():
    result = merge_override("%command% -dx11")
    assert result == 'WINEDLLOVERRIDES="dsound=n,b" %command% -dx11'


def test_merging_twice_changes_nothing():
    once = merge_override("MANGOHUD=1 %command%")
    assert merge_override(once) == once
