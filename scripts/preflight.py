"""Check the configuration the service would start with. Exit status 1 if there are errors.

    AKASH_ENV=prod uv run python scripts/preflight.py"""

from __future__ import annotations

import sys

from akash_core.config import Settings
from akash_core.preflight import check


def main() -> int:
    found = check(Settings())
    for x in found:
        print(f"{x.level.upper():7} {x.code}: {x.message}")
    errors = [x for x in found if x.level == "error"]
    print(f"{len(errors)} error(s), {len(found) - len(errors)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
