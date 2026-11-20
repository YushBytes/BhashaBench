"""Data access for bot integrations. Never commits; the service owns the transaction."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bot_integration import BotIntegration


def get(session: Session, integration_id: uuid.UUID) -> BotIntegration | None:
    return session.get(BotIntegration, integration_id)


def get_by_name(session: Session, project_id: uuid.UUID, name: str) -> BotIntegration | None:
    statement = select(BotIntegration).where(
        BotIntegration.project_id == project_id, BotIntegration.name == name
    )
    return session.scalars(statement).first()


def list_for_projects(session: Session, project_ids: Sequence[uuid.UUID]) -> list[BotIntegration]:
    """Integrations in `project_ids`, newest first. An empty scope lists nothing."""
    if not project_ids:
        return []
    statement = (
        select(BotIntegration)
        .where(BotIntegration.project_id.in_(project_ids))
        .order_by(BotIntegration.created_at.desc(), BotIntegration.id)
    )
    return list(session.scalars(statement))


def add(session: Session, integration: BotIntegration) -> BotIntegration:
    session.add(integration)
    session.flush()
    return integration


def delete(session: Session, integration: BotIntegration) -> None:
    session.delete(integration)
    session.flush()


__all__ = ["add", "delete", "get", "get_by_name", "list_for_projects"]
