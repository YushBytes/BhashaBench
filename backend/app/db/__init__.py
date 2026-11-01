"""Database engine, session management and the declarative base.

Kept separate from `app.models` so that importing a model does not create an
engine, and so Alembic can import metadata without starting the application.
"""
