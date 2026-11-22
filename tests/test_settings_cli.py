import json
import os

import pytest

from kaltui.auth import Credentials
from kaltui.cli import main
from kaltui.errors import KaltuiError
from kaltui.settings import Settings


def test_preferences_save_atomically_and_contain_only_public_state(tmp_path):
    path = tmp_path / "config" / "settings.json"
    settings = Settings(["PUBLIC-TICKER"], "stacked", 60)
    settings.save(path)
    assert Settings.load(path) == settings
    assert set(json.loads(path.read_text())) == {"favorites", "layout", "poll_seconds"}
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(".kaltui-*"))


def test_invalid_settings_fail_explicitly(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json")
    with pytest.raises(KaltuiError, match="--no-save"):
        Settings.load(path)


def test_settings_validate_and_deduplicate(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"favorites": ["TEST", "TEST", "../bad", 4], "layout": "bad", "poll_seconds": True}
        )
    )
    assert Settings.load(path) == Settings(["TEST"])


def test_incomplete_credentials_are_not_silently_ignored(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test")
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(KaltuiError, match="both"):
        Credentials.from_environment()


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_cli_information_needs_no_credentials(flag, capsys):
    with pytest.raises(SystemExit) as result:
        main([flag])
    assert result.value.code == 0
    assert "kaltui" in capsys.readouterr().out


@pytest.mark.parametrize("interval", ["1", "3601", "nan"])
def test_invalid_refresh_interval(interval):
    with pytest.raises(SystemExit) as result:
        main(["--poll-seconds", interval])
    assert result.value.code == 2


def test_non_interactive_launch_is_clear(capsys):
    assert main(["--demo"]) == 2
    assert "interactive terminal" in capsys.readouterr().err


def test_demo_settings_are_separate(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["--demo", "--paths"]) == 0
    assert "demo-settings.json" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["--demo", "--public"])
def test_public_and_demo_never_open_account_credentials(mode, monkeypatch):
    from kaltui.ui.app import KaltuiApp

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(KaltuiApp, "run", lambda self: None)

    def forbidden():
        pytest.fail("Credentials must not be opened in public or demo mode")

    monkeypatch.setattr(Credentials, "from_environment", forbidden)
    assert main([mode, "--no-save"]) == 0
