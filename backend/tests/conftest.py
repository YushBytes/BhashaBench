"""Shared pytest fixtures.

Database-backed tests run against a **real PostgreSQL**, not SQLite: the schema
uses JSONB, native UUIDs and `ON DELETE RESTRICT`, none of which SQLite models
faithfully. A suite that passed on SQLite would prove very little.

Isolation strategy. A dedicated `bhashabench_test` database is created once per
session and migrated with Alembic - which also exercises the migration itself.
Each test then runs inside a transaction that is rolled back afterwards, so
tests neither see each other's rows nor need to clean up. The developer's own
database is never touched.

If PostgreSQL is unreachable, the database-backed tests are skipped with an
explicit reason naming the host and port tried, and a session-end banner
reports how many were skipped. They are never silently passed. With
`BHASHABENCH_REQUIRE_DATABASE=1` - which CI sets - an unreachable database is
a failure instead of a skip; see `tests/db_gate.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_database_probe, get_principal, get_websocket_principal
from app.api.v1.transcription import get_service_factory
from app.auth import tokens
from app.auth.passwords import hash_password
from app.core.config import AppEnv, Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models.identity import Project, Role, User, Workspace, WorkspaceMembership
from app.models.suite import TestSuite as SuiteModel
from app.repositories import identity as identity_repo
from app.services.auth_service import Principal
from app.services.transcription_service import TranscriptionService
from app.transcription.providers.fake import FakeTranscriptionProvider
from app.utils.timing import utc_now
from tests.db_gate import database_required, database_unreachable

BACKEND_ROOT = Path(__file__).resolve().parents[1]

TEST_DB_NAME = "bhashabench_test"

_SKIP_REASON: str | None = None
"""Set when the database turns out to be unreachable, so every dependent test
reports the same concrete reason."""


# ---------------------------------------------------------------------------
# Settings / app fixtures (no database required)
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register Phase 4 markers.

    Declared here rather than in `pyproject.toml`/`pytest.ini` on purpose.
    `--strict-markers` requires registration, but `tests/test_tooling.py`
    asserts the host and container pytest configurations hold the same keys
    with the same whitespace-split values - and a marker line like
    `live: needs credentials` splits into words on one side and stays one
    string on the other. Registering in code keeps both configs identical and
    still satisfies strict markers.
    """
    config.addinivalue_line(
        "markers",
        "live: makes real, billable provider calls. Deselected unless "
        "TRANSCRIPTION_LIVE_TESTS=true and a credential is present.",
    )


CREDENTIAL_ENV_VARS: tuple[str, ...] = tuple(
    sorted(name.upper() for name in Settings.model_fields if name.endswith("_api_key"))
)
"""Environment variables that carry a provider credential, derived from the
settings model so a key added later is covered without editing this list."""


@pytest.fixture(autouse=True)
def _no_ambient_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hide provider credentials exported in the shell from every offline test.

    `_env_file=None` keeps a local `.env` out of a test's settings, but
    pydantic-settings still reads the process environment. A developer who
    exported `GNANI_API_KEY` to run the live tests then saw offline tests fail
    - and pytest's assertion diff printed the key. Only `live` tests, which
    are opt-in and need the real credential, keep it.
    """
    if request.node.get_closest_marker("live") is not None:
        return
    for name in CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Transcription fixtures (Phase 4) - no database, no network, no credentials
# ---------------------------------------------------------------------------

AUDIO_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audio"


@pytest.fixture(scope="session")
def audio_fixtures() -> Path:
    """Directory holding the committed audio fixtures."""
    return AUDIO_FIXTURES


@pytest.fixture(scope="session")
def wav_8k(audio_fixtures: Path) -> bytes:
    """A one-second 8 kHz mono WAV - the ordinary batch happy path."""
    return (audio_fixtures / "tone_8k_mono.wav").read_bytes()


@pytest.fixture(scope="session")
def wav_16k(audio_fixtures: Path) -> bytes:
    """A one-second 16 kHz mono WAV."""
    return (audio_fixtures / "tone_16k_mono.wav").read_bytes()


@pytest.fixture(scope="session")
def raw_pcm_8k(audio_fixtures: Path) -> bytes:
    """Headerless 8 kHz mono PCM, for the streaming path."""
    return (audio_fixtures / "raw_8k_mono.pcm").read_bytes()


@pytest.fixture
def fake_provider() -> FakeTranscriptionProvider:
    """An offline provider with default scripted behaviour."""
    return FakeTranscriptionProvider()


@pytest.fixture
def transcription_settings() -> Settings:
    """Settings that select the offline fake and retry fast.

    Backoff is driven to zero so retry-path tests do not spend real seconds
    sleeping; `tests/test_transcription_retry.py` asserts the delay arithmetic
    separately with an injected clock.
    """
    return Settings(
        app_env=AppEnv.TEST,
        app_version="0.1.0",
        secret_key="test-secret-key-not-used-for-anything",
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
        transcription_provider="fake",
        transcription_max_attempts=3,
        transcription_initial_backoff_seconds=0.0,
        transcription_max_backoff_seconds=0.0,
        _env_file=None,
    )


@pytest.fixture
def transcription_service(
    fake_provider: FakeTranscriptionProvider, transcription_settings: Settings
) -> TranscriptionService:
    """A service wired to the offline fake."""
    return TranscriptionService(fake_provider, settings=transcription_settings)


@pytest.fixture
def transcription_client(
    transcription_settings: Settings, fake_provider: FakeTranscriptionProvider
) -> Iterator[TestClient]:
    """HTTP client whose transcription routes use the offline fake.

    Overrides the service dependency rather than the provider registry, so the
    test drives the real route, the real request parsing and the real error
    handlers - only the vendor call is replaced.
    """
    app = create_app(settings=transcription_settings)
    app.dependency_overrides[get_settings] = lambda: transcription_settings
    app.dependency_overrides[get_database_probe] = lambda: (
        lambda: (True, "Connected; SELECT 1 succeeded.")
    )
    # One override covers both the HTTP and the WebSocket route.
    app.dependency_overrides[get_service_factory] = lambda: (
        lambda: TranscriptionService(fake_provider, settings=transcription_settings)
    )
    authenticate_without_database(app)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings for tests, independent of any local `.env`."""
    return Settings(
        app_env=AppEnv.TEST,
        app_version="0.1.0",
        secret_key="test-secret-key-not-used-for-anything",
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
        # scrypt at N=2^10 instead of 2^17, so each login costs milliseconds;
        # Settings refuses this value in staging and production.
        auth_password_hash_log2_n=10,
        # No background recovery sweep in tests; it is exercised directly.
        pipeline_recovery_interval_seconds=0,
        _env_file=None,
    )


@pytest.fixture
def test_app(settings: Settings) -> FastAPI:
    """An application instance built against the test settings.

    The database probe is stubbed to report reachable. Left un-stubbed it
    would use the process-wide engine built from global settings, so the
    health endpoint would report on whatever database the developer's `.env`
    points at - making the result depend on the machine rather than the test.
    Tests that care about the probe override it themselves.
    """
    app = create_app(settings=settings)
    # Routes resolve settings via dependency injection; override it so they
    # see the same object the app was constructed with.
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_database_probe] = lambda: (
        lambda: (True, "Connected; SELECT 1 succeeded.")
    )
    return app


OFFLINE_PRINCIPAL = Principal(
    user_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
    email="offline@example.test",
    display_name="Offline test principal",
    session_id=None,
)
"""The caller for clients with no database. Authentication needs a session
row, so routes that hold no tenant data (transcription, speech) are driven as
this principal through a dependency override. The override is a test seam:
nothing outside tests can bypass `get_principal`."""


def authenticate_without_database(app: FastAPI) -> None:
    app.dependency_overrides[get_principal] = lambda: OFFLINE_PRINCIPAL
    app.dependency_overrides[get_websocket_principal] = lambda: OFFLINE_PRINCIPAL


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """HTTP client that runs the app's lifespan, as a real server would.

    No database is wired in, so this client serves the Phase 1 endpoints. API
    tests that need persistence use `api_client` instead.
    """
    authenticate_without_database(test_app)
    with TestClient(test_app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


def _admin_url(url: str) -> str:
    """Return the same server URL pointed at the maintenance database.

    `CREATE DATABASE` cannot run while connected to the database being
    created, so connect to `postgres` instead.
    """
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/postgres"))


def _test_url(url: str) -> str:
    """Return the same server URL pointed at the test database."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{TEST_DB_NAME}"))


def _source_url() -> str:
    """Return the base database URL to derive the test database from.

    `BHASHABENCH_TEST_DATABASE_URL` wins so CI can point at its own service;
    otherwise the application's configured `DATABASE_URL` is used, which on a
    developer machine is the Docker Compose database.
    """
    override = os.getenv("BHASHABENCH_TEST_DATABASE_URL")
    if override:
        return override

    get_settings.cache_clear()
    try:
        return get_settings().database_url
    finally:
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def database_url() -> str:
    """Create and migrate a dedicated test database; drop it afterwards.

    Skips - loudly, with the host and port in the reason - when the server is
    unreachable.
    """
    global _SKIP_REASON

    base = _source_url()
    url = make_url(base)
    where = f"{url.host}:{url.port}"

    # A short connect timeout keeps the no-database path fast: without it a
    # closed port is retried across both address families with the driver's
    # default timeout, turning a CI run with no database into minutes of
    # waiting before the skip.
    admin = create_engine(
        _admin_url(base),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        _SKIP_REASON = (
            f"PostgreSQL unreachable at {where} ({type(exc).__name__}). "
            "Database-backed tests were SKIPPED, not passed. "
            "Start it with: docker compose up -d db"
        )
        admin.dispose()
        database_unreachable(_SKIP_REASON, required=database_required())

    target = _test_url(base)

    with admin.connect() as connection:
        # Terminate leftover sessions from an interrupted previous run, or the
        # DROP below blocks forever.
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": TEST_DB_NAME},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
        connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    # Migrate with Alembic rather than create_all(), so the migration itself is
    # exercised on every run and cannot drift from the models unnoticed.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": target},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        admin.dispose()
        pytest.fail(
            "alembic upgrade head failed against the test database:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    yield target

    with admin.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": TEST_DB_NAME},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_engine(database_url: str) -> Iterator[Engine]:
    """Engine bound to the migrated test database."""
    engine = create_engine(database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back.

    The session is bound to an explicit connection with an open transaction.
    Anything the test commits lands inside that outer transaction, and the
    rollback at the end discards it - so `commit()` in service code behaves
    normally while leaving no trace between tests.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    event.listen(session, "before_flush", _default_suite_project)

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# The default tenant (Phase 14)
# ---------------------------------------------------------------------------

TENANT_KEY = "bhashabench.test_tenant"


def default_tenant(session: Session, *, flush: bool = True) -> tuple[User, Workspace, Project]:
    """One owner, workspace and `Default` project per test, created on demand.

    Tests that are not about tenancy create suites without naming a project
    and call the API through `api_client`; both land here, so they behave as
    one workspace's owner would. Tests that ARE about tenancy build their own
    users and workspaces (`tests/auth_helpers.py`) and never rely on this.
    """
    cached = session.info.get(TENANT_KEY)
    if cached is not None and all(
        (state := inspect(obj)).persistent or state.pending for obj in cached
    ):
        return cached
    # Absent, or rolled back with a failed flush (which detaches the rows):
    # create it again rather than point a suite at a project that is gone.
    tag = uuid.uuid4().hex[:10]
    # Explicit ids, so the rows can join a flush already in progress (the
    # `before_flush` hook below) without flushing re-entrantly.
    user = User(
        id=uuid.uuid4(),
        email=f"owner-{tag}@example.test",
        display_name="Default test owner",
        password_hash=hash_password("default test owner password", log2_n=10),
    )
    workspace = Workspace(id=uuid.uuid4(), name="Default test workspace", slug=f"test-{tag}")
    project = Project(id=uuid.uuid4(), workspace_id=workspace.id, name="Default")
    membership = WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER)
    session.add_all([user, workspace, project, membership])
    if flush:
        session.flush()
    session.info[TENANT_KEY] = (user, workspace, project)
    return user, workspace, project


def _default_suite_project(session: Session, _context: object, _instances: object) -> None:
    """A suite flushed without a project goes to the default tenant's."""
    pending = [o for o in session.new if isinstance(o, SuiteModel) and o.project_id is None]
    if pending:
        _, _, project = default_tenant(session, flush=False)
        for suite in pending:
            suite.project_id = project.id


@pytest.fixture
def tenant(db_session: Session) -> tuple[User, Workspace, Project]:
    return default_tenant(db_session)


def bearer_for(session: Session, user: User) -> dict[str, str]:
    """A live session for `user`, created directly rather than by logging in."""
    token = tokens.new_token()
    now = utc_now()
    identity_repo.add_session(
        session,
        user_id=user.id,
        token_hash=tokens.token_hash(token),
        now=now,
        expires_at=now + timedelta(hours=1),
    )
    session.flush()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api_client(test_app: FastAPI, db_session: Session) -> Iterator[TestClient]:
    """HTTP client whose requests share the test's rolled-back session.

    Overriding `get_db` is what keeps API tests isolated: handlers commit as
    usual, but everything happens inside the fixture's outer transaction.
    """

    def override_get_db() -> Iterator[Session]:
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    owner, _, _ = default_tenant(db_session)
    with TestClient(test_app) as test_client:
        # Signed in as the default tenant's owner. A test about authentication
        # uses `anonymous`, which drops this header, and presents its own.
        test_client.headers.update(bearer_for(db_session, owner))
        yield test_client
    test_app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def anonymous(api_client: TestClient) -> TestClient:
    """`api_client` with no credential: what an unauthenticated caller sees."""
    api_client.headers.pop("Authorization", None)
    return api_client


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Report skipped database tests prominently rather than letting them pass quietly."""
    if _SKIP_REASON:
        writer = session.config.get_terminal_writer()
        writer.line("")
        writer.line("=" * 72, yellow=True)
        writer.line("ENVIRONMENTAL LIMITATION - database tests did not run", yellow=True)
        writer.line(_SKIP_REASON, yellow=True)
        writer.line("=" * 72, yellow=True)
