"""Reading and writing the deployment's `.env`, a few lines at a time (Phase 20).

The API sees the server's `.env` at `ENV_FILE_PATH` (mounted by
docker-compose.yml). It changes **only the lines it is asked to** — the hosting
lines in `hosting_config.MANAGED` — and leaves everything else exactly as it
was: comments, order, blank lines, the secrets, and the file's own line
endings.

Written in place, never replaced: a single file bind-mounted into a container
is pinned to the original file, and the usual write-a-temporary-then-rename
would leave the container writing to a file the host no longer sees.

Nothing here decides anything. It reads and writes; `hosting_config` decides.
"""

from __future__ import annotations

import os
import re

#: Where docker-compose.yml mounts the server's .env inside the API container.
#: Read at each call (not bound as a default), so tests can point it away.
ENV_FILE_PATH = os.environ.get("GOALGETTER_ENV_FILE", "/run/goalgetter/.env")


def _path(path: str | None) -> str:
    return path or ENV_FILE_PATH


_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def readable(path: str | None = None) -> bool:
    """Whether the file is there to read: then its edits are followed."""
    path = _path(path)
    return os.path.isfile(path) and os.access(path, os.R_OK)


def writable(path: str | None = None) -> bool:
    """Whether the app may also write it: then it is kept in step both ways.

    **Read without being writable is a real state** (P7-2): on Linux `.env`
    belongs to whoever ran setup — root, after `sudo` — and the API is uid
    1000. Edits made in the file are still followed then; only writing stops.
    """
    path = _path(path)
    return readable(path) and os.access(path, os.W_OK)


def read(path: str | None = None) -> dict[str, str]:
    """Every KEY=value line, as written (no quotes are interpreted)."""
    with open(_path(path), encoding="utf-8", newline="") as handle:
        text = handle.read()
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def write(changes: dict[str, str], path: str | None = None) -> None:
    """Set these keys, in place. Missing ones are added at the end."""
    if not changes:
        return
    path = _path(path)
    for key, value in changes.items():
        # One line each, or the file stops being one line per setting.
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} cannot contain a line break")

    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    remaining = dict(changes)
    for index, line in enumerate(lines):
        match = _LINE.match(line.strip())
        if match and match.group(1) in remaining:
            key = match.group(1)
            lines[index] = f"{key}={remaining.pop(key)}"
    if remaining:
        # Before a trailing empty line, so the file still ends in a newline.
        tail = [f"{key}={value}" for key, value in remaining.items()]
        if lines and lines[-1] == "":
            lines[-1:-1] = tail
        else:
            lines.extend(tail)
    updated = newline.join(lines)

    # In place: see the module docstring.
    with open(path, "r+", encoding="utf-8", newline="") as handle:
        handle.seek(0)
        handle.write(updated)
        handle.truncate()
