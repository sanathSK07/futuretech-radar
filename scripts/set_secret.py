#!/usr/bin/env python3
"""Put a secret into .env without it appearing on screen or in shell history.

Pasting a credential into a terminal writes it to ~/.zsh_history. Pasting it
into a chat, an issue or a screenshot publishes it. This reads the value from a
hidden prompt and writes it straight to .env, so the only places it exists are
the provider's console and the file that needs it.

    python3 scripts/set_secret.py RADAR_ANTHROPIC_API_KEY

The key is created or replaced in place; every other line in .env is untouched.
Nothing here is a secret, so it belongs in the repository.
"""

from __future__ import annotations

import os
import sys
import tempfile
from getpass import getpass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Keys this script is allowed to set, so a typo cannot quietly create
# RADAR_ANTROPIC_API_KEY and leave you debugging an empty setting.
KNOWN_KEYS = {
    "RADAR_ANTHROPIC_API_KEY",
    "RADAR_DATABASE_URL",
    "RADAR_TEST_DATABASE_URL",
    "RADAR_CRAWLER_CONTACT",
}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <KEY> [path-to-.env]", file=sys.stderr)
        print(f"known keys: {', '.join(sorted(KNOWN_KEYS))}", file=sys.stderr)
        return 2

    key = sys.argv[1].strip()
    if key not in KNOWN_KEYS:
        print(
            f"{key} is not a known setting. One of: {', '.join(sorted(KNOWN_KEYS))}",
            file=sys.stderr,
        )
        return 2

    env_path = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_ROOT / ".env"
    if not env_path.is_file():
        print(f"no such file: {env_path}. Run 'make setup' first.", file=sys.stderr)
        return 1

    value = getpass(f"{key} (input hidden): ")
    confirm = getpass("Again, to catch a truncated paste: ")
    if not value:
        print("empty value; nothing changed", file=sys.stderr)
        return 1
    if value != confirm:
        print("the two entries differ; nothing changed", file=sys.stderr)
        return 1
    if "\n" in value:
        print("the value contains a newline; nothing changed", file=sys.stderr)
        return 1

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    replaced = False
    for line in lines:
        name, sep, _ = line.partition("=")
        if sep and name.strip() == key:
            out.append(f"{key}={value}\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(f"{key}={value}\n")

    fd, tmp_name = tempfile.mkstemp(dir=env_path.parent, prefix=".env.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(out))
        os.replace(tmp_name, env_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    os.chmod(env_path, 0o600)

    action = "replaced" if replaced else "added"
    print(f"{action} {key} in {env_path} ({len(value)} characters). Its value was not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
