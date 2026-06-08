"""Tests for `st ui key` key-name translation.

ydotool 0.1.8 only recognizes a curated subset of key names; an unrecognized
token (e.g. `Return`, `Escape`, `space`) silently degrades to the keycode of its
first character, so `st ui key Return` used to type "r". `_ydotool_chord` maps
the X11/xdotool names callers type onto the tokens ydotool actually recognizes,
per-token so chords keep working. The ydotool subprocess is mocked; we assert on
the translated argument it would receive.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import ui as ui_mod
from cli.commands.ui import _ydotool_chord
from cli.commands.ui import app as ui_app

runner = CliRunner()


def test_chord_translates_bare_named_keys():
    # The reported bug: these used to reach ydotool verbatim and type r/e/etc.
    assert _ydotool_chord("Return") == "enter"
    assert _ydotool_chord("Escape") == "esc"
    assert _ydotool_chord("Page_Up") == "pageup"
    assert _ydotool_chord("del") == "delete"
    assert _ydotool_chord("space") == " "


def test_chord_is_case_insensitive():
    assert _ydotool_chord("RETURN") == "enter"
    assert _ydotool_chord("escape") == "esc"


def test_chord_maps_each_token_in_a_chord():
    # Modifiers and native tokens pass through; only aliased keys are rewritten.
    assert _ydotool_chord("ctrl+Return") == "ctrl+enter"
    assert _ydotool_chord("ctrl+shift+Escape") == "ctrl+shift+esc"


def test_chord_passes_through_recognized_tokens():
    # Already-valid ydotool input must be left exactly as-is (no regressions).
    for chord in ("ctrl+c", "ctrl+shift+p", "alt+F4", "enter", "tab", "a"):
        assert _ydotool_chord(chord) == chord


def test_key_command_sends_translated_chord():
    with patch.object(ui_mod, "_ydotool") as mock_ydo:
        result = runner.invoke(ui_app, ["key", "Return"])
    assert result.exit_code == 0, result.output
    mock_ydo.assert_called_once_with(["key", "enter"])
    # Success message echoes what the caller asked for, not the translated form.
    assert "sent Return" in result.output


def test_key_command_preserves_working_chord():
    with patch.object(ui_mod, "_ydotool") as mock_ydo:
        result = runner.invoke(ui_app, ["key", "ctrl+shift+p"])
    assert result.exit_code == 0, result.output
    mock_ydo.assert_called_once_with(["key", "ctrl+shift+p"])
