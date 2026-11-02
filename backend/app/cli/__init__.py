"""The `bhashabench` command-line interface.

A thin front end over the same services the API uses. It owns no validation,
no SQL and no business rules of its own - duplicating any of those would mean
the CLI and the API could disagree about whether a scenario is valid, which is
the one thing a test-authoring tool must never do.

Two classes of command:

* **Offline** - `validate`, `validate-bundle`, `languages`. These touch only
  the parser and the catalogue, so they work with no PostgreSQL running. That
  matters because the common case is an author checking a file, and because
  CI should be able to reject a malformed scenario before any service exists.
* **Database-backed** - everything under `suite` and `scenario`, plus `import`
  and `export`. These resolve configuration through the existing
  `app.core.config` settings and open a session through `app.db.session`, so
  there is no second connection story and no credential handling here.

Exit codes are meaningful, because a CLI's real consumer is a shell script:

    0  success
    1  an operation failed (not found, conflict, refused)
    2  invalid input (bad YAML, failed validation, bad arguments)
    3  the database is unreachable
"""

from app.cli.main import app, main

__all__ = ["app", "main"]
