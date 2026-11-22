"""Non-secret local preferences. Account responses and credentials are never saved."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_path

from .errors import KaltuiError
from .parsing import TICKER


def settings_path() -> Path:
    return user_config_path("kaltui", appauthor=False) / "settings.json"


@dataclass
class Settings:
    favorites: list[str] = field(default_factory=list)
    layout: str = "classic"
    poll_seconds: int = 30

    @classmethod
    def load(cls, path: Path) -> Settings:
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return cls()
        except PermissionError:
            raise KaltuiError(
                "OS permission denied reading settings. Fix permissions before continuing."
            ) from None
        except (OSError, ValueError):
            raise KaltuiError(
                "Cannot read settings. Move the settings file aside or use --no-save."
            ) from None
        if not isinstance(data, dict):
            raise KaltuiError(
                "Invalid settings format; use --no-save or move the settings file aside."
            )
        favorites = data.get("favorites", [])
        favorites = favorites if isinstance(favorites, list) else []
        favorites = list(
            dict.fromkeys(
                item for item in favorites if isinstance(item, str) and TICKER.fullmatch(item)
            )
        )[:100]
        poll = data.get("poll_seconds", 30)
        poll = poll if type(poll) is int and 10 <= poll <= 3600 else 30
        layout = data.get("layout", "classic")
        return cls(favorites, layout if layout in ("classic", "stacked") else "classic", poll)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, prefix=".kaltui-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                json.dump(asdict(self), handle, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
