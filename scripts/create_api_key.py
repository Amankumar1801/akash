"""Create an API key. The full key is printed ONCE and only its hash is stored.

    uv run python scripts/create_api_key.py --name alice --role researcher
Roles: viewer (read), researcher (+ run investigations), admin (+ see everyone's)."""

from __future__ import annotations

import argparse

from akash_api.auth import ROLES, ApiKeyStore
from akash_api.db import open_connection
from akash_core.config import Settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="identity; investigations are owned by name")
    ap.add_argument("--role", required=True, choices=sorted(ROLES))
    a = ap.parse_args()
    conn = open_connection(Settings().sqlite_path)
    key = ApiKeyStore(conn).create(a.name, a.role)
    print(f"API key for {a.name} ({a.role}). Store it now; it cannot be shown again:\n{key}")


if __name__ == "__main__":
    main()
