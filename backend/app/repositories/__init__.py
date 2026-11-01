"""Data access.

Every SQL statement in the application lives in this package. Services
orchestrate and apply rules; repositories only read and write. The split keeps
`select()` calls out of route handlers and gives the service layer a seam that
can be faked in tests without a database.

Repository functions take an explicit `Session` and never commit. Transaction
boundaries belong to the caller, so a service can perform several writes and
commit them together or not at all.
"""
