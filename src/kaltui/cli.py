"""Terminal entry point, offline demo, and optional private account reads."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .auth import Credentials
from .errors import KaltuiError
from .parsing import ticker
from .settings import Settings, settings_path


def interval(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("refresh interval must be an integer") from None
    if not 10 <= result <= 3600:
        raise argparse.ArgumentTypeError("refresh interval must be between 10 and 3600 seconds")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="kaltui — a read-only Kalshi terminal dashboard")
    parser.add_argument("--version", action="version", version=f"kaltui {__version__}")
    parser.add_argument(
        "--demo", action="store_true", help="offline synthetic demo; ignores credentials"
    )
    parser.add_argument(
        "--public", action="store_true", help="public markets only; ignores credentials"
    )
    parser.add_argument("--series", default="", help="initial Kalshi series ticker")
    parser.add_argument(
        "--poll-seconds", type=interval, default=None, help="refresh interval, 10–3600 (default 30)"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="do not read or write local preferences"
    )
    parser.add_argument("--paths", action="store_true", help="print local settings paths and exit")
    args = parser.parse_args(argv)
    path = settings_path()
    if args.demo:
        path = path.with_name("demo-settings.json")
    if args.paths:
        print(path)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "kaltui requires an interactive terminal. Try ./run.sh --demo in a terminal.",
            file=sys.stderr,
        )
        return 2
    try:
        if args.series:
            ticker(args.series)
        settings = Settings() if args.no_save else Settings.load(path)
        if args.poll_seconds is not None:
            settings.poll_seconds = args.poll_seconds
        credentials = None if args.demo or args.public else Credentials.from_environment()
    except KaltuiError as exc:
        print(f"kaltui: {exc}", file=sys.stderr)
        return 2
    from .client import KalshiClient
    from .demo import DemoClient
    from .ui.app import KaltuiApp

    app = KaltuiApp(
        DemoClient() if args.demo else KalshiClient(credentials),
        settings,
        settings_file=None if args.no_save else path,
        demo=args.demo,
        series=args.series,
    )
    app.run()
    return 0
