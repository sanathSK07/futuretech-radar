#!/usr/bin/env python3
"""Replace the password in the .env database URLs, without it reaching the screen.

Hand-editing a connection string is how a stray character ends up in a secret
you cannot read back, and pasting a rotated password into a terminal echoes it
into the shell history. This reads the new password from a no-echo prompt,
substitutes it into every database URL in .env, and prints nothing but the
hosts it touched.

    python scripts/rotate_db_password.py

Rotation itself happens in the provider's console; this only updates the local
file afterwards. Nothing here is a secret, so it belongs in the repository.
"""

from __future__ import annotations

import os
import sys
import tempfile
from getpass import getpass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

# Every key whose value is a database URL. Add to this list rather than
# teaching the script to guess from the value.
URL_KEYS = ("RADAR_DATABASE_URL", "RADAR_TEST_DATABASE_URL")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def replace_password(url: str, password: str) -> tuple[str, str]:
    """Return the URL with its password replaced, and the host it points at."""
    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError("no host in URL")
    if not parts.username:
        raise ValueError("no username in URL; nothing to attach a password to")

    # quote() because a generated password may contain characters that would
    # otherwise end the userinfo section early and silently truncate the URL.
    userinfo = f"{parts.username}:{quote(password, safe='')}"
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    rebuilt = urlunsplit(
        (parts.scheme, f"{userinfo}@{host}", parts.path, parts.query, parts.fragment)
    )
    return rebuilt, host


def main() -> int:
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / ".env"
    if not env_path.is_file():
        print(f"no such file: {env_path}", file=sys.stderr)
        return 1

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)

    password = getpass("New database password (input hidden): ")
    confirm = getpass("Again, to catch a typo: ")
    if not password:
        print("empty password; nothing changed", file=sys.stderr)
        return 1
    if password != confirm:
        print("the two entries differ; nothing changed", file=sys.stderr)
        return 1

    updated: list[str] = []
    out: list[str] = []
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() in URL_KEYS and value.strip():
            try:
                new_url, host = replace_password(value.strip(), password)
            except ValueError as exc:
                print(f"{key.strip()}: {exc}; nothing changed", file=sys.stderr)
                return 1
            updated.append(f"{key.strip()} -> {host}")
            out.append(f"{key.strip()}={new_url}\n")
        else:
            out.append(line)

    if not updated:
        print(f"no database URLs found in {env_path}; nothing changed", file=sys.stderr)
        return 1

    # Write through a temporary file in the same directory so an interrupted run
    # cannot leave a half-written .env, and create it 0600 so the secret is never
    # briefly world-readable.
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

    print(f"updated {len(updated)} URL(s) in {env_path}:")
    for entry in updated:
        print(f"  {entry}")
    print("\nNow run: make check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
