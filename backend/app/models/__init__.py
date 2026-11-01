"""Database models.

Every model is imported here so that a single `import app.models` populates
`Base.metadata` completely. Alembic's `env.py` relies on this: autogenerate
can only see tables whose classes have been imported, and a model that is
missing from this list silently disappears from migrations.
"""

from app.db.base import Base
from app.models.call_session import CallSession, CallStatus
from app.models.conversation_turn import ConversationTurn, Speaker
from app.models.scenario import Scenario
from app.models.suite import TestSuite
from app.models.test_run import RunStatus, TestRun

__all__ = [
    "Base",
    "CallSession",
    "CallStatus",
    "ConversationTurn",
    "RunStatus",
    "Scenario",
    "Speaker",
    "TestRun",
    "TestSuite",
]
