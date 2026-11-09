"""Count the API surface from the OpenAPI schema.

Walking `app.routes` does **not** work: the installed FastAPI mounts included
routers lazily as internal `_IncludedRouter` objects instead of flattening
their routes onto the application, so the walk yields only the handful of
routes declared directly on `app` and reads as "the v1 API is not mounted".
The generated OpenAPI document is the authority, and this script is the only
place the figures quoted in the documentation come from.

One WebSocket route (`/api/v1/transcription/stream`) is deliberately absent
from the schema: OpenAPI 3.1 cannot describe a WebSocket. It is therefore not
counted here, and the documentation states it separately.

Usage:
    python scripts/api_surface.py            # human-readable summary
    python scripts/api_surface.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# The OpenAPI 3.1 fixed fields of a Path Item Object that are *not* operations.
# Anything else at that level is an HTTP operation.
_NON_OPERATION_KEYS = frozenset({"$ref", "summary", "description", "servers", "parameters"})

# The HTTP methods OpenAPI 3.1 defines for a Path Item Object.
_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _load_schema() -> dict[str, Any]:
    """Import the application and generate its OpenAPI document."""
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "backend"))
    # The app refuses to start on the placeholder secret; supply a throwaway
    # one so the schema can be generated without a configured environment.
    os.environ.setdefault("SECRET_KEY", "x" * 40)

    from app.main import app

    return app.openapi()


def summarise(schema: dict[str, Any]) -> dict[str, Any]:
    """Reduce an OpenAPI document to path and operation counts.

    Operations are counted by subtracting the Path Item Object's fixed
    non-operation fields rather than by matching a method allow-list, so a
    method this script has not heard of is still counted. Any such key is
    reported in `unexpected_keys` so a silent miscount is impossible.
    """
    paths: dict[str, Any] = schema.get("paths", {})
    per_path: dict[str, list[str]] = {}
    unexpected: dict[str, list[str]] = {}

    for path, item in sorted(paths.items()):
        keys = {k.lower() for k in item} - _NON_OPERATION_KEYS
        per_path[path] = sorted(keys)
        strange = sorted(keys - _HTTP_METHODS)
        if strange:
            unexpected[path] = strange

    return {
        "paths": len(per_path),
        "operations": sum(len(ops) for ops in per_path.values()),
        "per_path": per_path,
        "unexpected_keys": unexpected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    result = summarise(_load_schema())

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print(f"paths:      {result['paths']}")
    print(f"operations: {result['operations']}")
    print()
    for path, ops in result["per_path"].items():
        print(f"  {' '.join(op.upper() for op in ops):<22} {path}")

    if result["unexpected_keys"]:
        print()
        print("WARNING: path items carry keys this script does not classify:")
        for path, keys in result["unexpected_keys"].items():
            print(f"  {path}: {', '.join(keys)}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
