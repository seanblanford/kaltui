#!/bin/sh
# Use an isolated local environment. Set up dependencies on the first run.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
if [ ! -x "$project_dir/.venv/bin/python" ]; then
    python3 -m venv "$project_dir/.venv"
fi
if ! "$project_dir/.venv/bin/python" -c 'import kaltui, textual, httpx, cryptography' >/dev/null 2>&1; then
    "$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
fi
exec "$project_dir/.venv/bin/python" -m kaltui "$@"
