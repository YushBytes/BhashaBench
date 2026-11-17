"""Phase 10 signed, expiring audio links: the HMAC primitive, then minting
and using links through the real routes, including revocation."""

from __future__ import annotations

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import signing
from app.core.config import Settings
from app.models.identity import Role
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.utils.timing import utc_now
from tests import test_pipeline_api as pipeline_tests
from tests.auth_helpers import make_user
from tests.conftest import default_tenant

pipeline_client = pipeline_tests.pipeline_client
scenario_ids = pipeline_tests.scenario_ids
wav = pipeline_tests.wav
BASE = pipeline_tests.BASE
SECRET = "a-test-secret-for-signing-only"
PATH = "/api/v1/test-runs/x/artifacts/0/audio"


def _parts(query: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(query).items()}


class TestPrimitive:
    def _mint(self, **kw: object) -> tuple[dict[str, str], uuid.UUID]:
        user = uuid.uuid4()
        query, _ = signing.mint(
            SECRET, path=PATH, variant=kw.get("variant"), user_id=user, now=utc_now()
        )  # type: ignore[arg-type]
        return _parts(query), user

    def _verify(
        self, parts: dict[str, str], *, path: str = PATH, now_shift: float = 0, secret: str = SECRET
    ) -> signing.LinkClaims:
        return signing.verify(
            secret, path=path, variant=parts.get("variant"), expires=parts["expires"],
            user=parts["user"], signature=parts["signature"],
            now=utc_now() + timedelta(seconds=now_shift),
        )  # fmt: skip

    def test_a_fresh_link_verifies(self) -> None:
        parts, user = self._mint(variant="degraded")
        assert self._verify(parts).user_id == user

    @pytest.mark.parametrize(
        "tamper",
        [
            lambda p: {**p, "variant": "original"},
            lambda p: {**p, "expires": str(int(p["expires"]) + 60)},
            lambda p: {**p, "user": str(uuid.uuid4())},
            lambda p: {**p, "signature": p["signature"][:-2] + "AA"},
        ],
    )
    def test_any_edit_breaks_it(self, tamper) -> None:
        parts, _ = self._mint(variant="degraded")
        with pytest.raises(signing.InvalidSignatureError):
            self._verify(tamper(parts))

    def test_it_opens_only_its_own_path(self) -> None:
        parts, _ = self._mint()
        with pytest.raises(signing.InvalidSignatureError):
            self._verify(parts, path="/api/v1/test-runs/x/artifacts/1/audio")

    def test_it_expires(self) -> None:
        parts, _ = self._mint()
        with pytest.raises(signing.InvalidSignatureError, match="expired"):
            self._verify(parts, now_shift=signing.DEFAULT_TTL.total_seconds() + 1)

    def test_a_rotated_secret_revokes_every_link(self) -> None:
        parts, _ = self._mint()
        with pytest.raises(signing.InvalidSignatureError):
            self._verify(parts, secret="the-next-secret")

    def test_lifetimes_are_bounded(self) -> None:
        with pytest.raises(ValueError):
            signing.mint(
                SECRET,
                path=PATH,
                variant=None,
                user_id=uuid.uuid4(),
                now=utc_now(),
                ttl=timedelta(hours=1),
            )

    def test_malformed_values_are_refused_not_raised(self) -> None:
        with pytest.raises(signing.InvalidSignatureError):
            signing.verify(
                SECRET,
                path=PATH,
                variant=None,
                expires="soon",
                user="me",
                signature="x",
                now=utc_now(),
            )


class TestThroughTheApi:
    @pytest.fixture
    def run_id(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes
    ) -> str:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = pipeline_tests._create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        assert pipeline_client.post(f"{BASE}/{run['run_id']}/start").status_code == 200
        return run["run_id"]

    def test_a_link_opens_the_audio_without_a_session(
        self, pipeline_client: TestClient, run_id: str
    ) -> None:
        minted = pipeline_client.post(
            f"{BASE}/{run_id}/audio-links", json={"turn_index": 0, "variant": "original"}
        )
        assert minted.status_code == 200, minted.text
        url = minted.json()["url"]
        assert url.startswith(f"/api/v1/test-runs/{run_id}/artifacts/0/audio?")
        served = pipeline_client.get(url, headers={"Authorization": ""})
        assert served.status_code == 200
        assert served.content[:4] == b"RIFF"

    def test_a_link_to_the_recording(self, pipeline_client: TestClient, run_id: str) -> None:
        url = pipeline_client.post(f"{BASE}/{run_id}/audio-links", json={}).json()["url"]
        assert urlsplit(url).path.endswith("/recording/audio")
        assert pipeline_client.get(url, headers={"Authorization": ""}).status_code == 200

    def test_a_link_cannot_be_redirected_to_another_turn(
        self, pipeline_client: TestClient, run_id: str
    ) -> None:
        url = pipeline_client.post(
            f"{BASE}/{run_id}/audio-links", json={"turn_index": 0, "variant": "original"}
        ).json()["url"]
        moved = url.replace("/artifacts/0/", "/artifacts/1/")
        assert pipeline_client.get(moved, headers={"Authorization": ""}).status_code == 401

    def test_a_tampered_link_is_401(self, pipeline_client: TestClient, run_id: str) -> None:
        url = pipeline_client.post(
            f"{BASE}/{run_id}/audio-links", json={"turn_index": 0, "variant": "original"}
        ).json()["url"]
        response = pipeline_client.get(
            url.replace("variant=original", "variant=degraded"), headers={"Authorization": ""}
        )
        assert response.status_code == 401
        assert "not valid" in response.json()["error"]["message"]

    def test_removing_the_minter_revokes_their_links(
        self, pipeline_client: TestClient, run_id: str, db_session: Session, settings: Settings
    ) -> None:
        _, workspace, _ = default_tenant(db_session)
        viewer, _ = make_user(
            db_session, settings, pipeline_client, workspace=workspace, role=Role.VIEWER
        )
        url = pipeline_client.post(
            f"{BASE}/{run_id}/audio-links",
            headers=viewer.headers,
            json={"turn_index": 0, "variant": "original"},
        ).json()["url"]
        assert pipeline_client.get(url, headers={"Authorization": ""}).status_code == 200
        removed = pipeline_client.delete(
            f"/api/v1/workspaces/{workspace.id}/members/{viewer.user.id}"
        )
        assert removed.status_code == 204
        assert pipeline_client.get(url, headers={"Authorization": ""}).status_code == 404

    def test_an_outsider_cannot_mint(
        self, pipeline_client: TestClient, run_id: str, db_session: Session, settings: Settings
    ) -> None:
        outsider, _ = make_user(db_session, settings, pipeline_client)
        response = pipeline_client.post(
            f"{BASE}/{run_id}/audio-links", headers=outsider.headers, json={}
        )
        assert response.status_code == 404

    def test_no_link_for_audio_that_does_not_exist(
        self, pipeline_client: TestClient, run_id: str
    ) -> None:
        assert (
            pipeline_client.post(
                f"{BASE}/{run_id}/audio-links", json={"turn_index": 99}
            ).status_code
            == 404
        )

    def test_the_lifetime_is_capped_at_fifteen_minutes(
        self, pipeline_client: TestClient, run_id: str
    ) -> None:
        assert (
            pipeline_client.post(
                f"{BASE}/{run_id}/audio-links", json={"ttl_seconds": 3600}
            ).status_code
            == 422
        )
