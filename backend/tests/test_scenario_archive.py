"""Scenario deletion and archival: history is never orphaned.

A scenario with recorded runs once answered DELETE with a 500 (the
RESTRICT foreign key from call_sessions surfaced unhandled). It is now a
409 naming the remedy, archival hides it without breaking its runs, and an
archived scenario cannot start a new run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.call_session import CallSession, CallStatus
from app.models.test_run import TestRun as RunModel

YAML = (Path(__file__).resolve().parents[2] / "scenarios" / "appointment_booking.yaml").read_text(
    encoding="utf-8"
)


def _scenario(client: TestClient) -> tuple[str, str]:
    suite = client.post("/api/v1/suites", json={"name": f"s-{uuid.uuid4().hex[:6]}"}).json()
    created = client.post(f"/api/v1/suites/{suite['id']}/scenarios", json={"yaml": YAML})
    assert created.status_code == 201, created.text
    return suite["id"], created.json()["id"]


def _record_a_run(db_session: Session, suite_id: str, scenario_id: str) -> None:
    run = RunModel(suite_id=uuid.UUID(suite_id))
    db_session.add(run)
    db_session.flush()
    db_session.add(
        CallSession(
            test_run_id=run.id, scenario_id=uuid.UUID(scenario_id), status=CallStatus.COMPLETED
        )
    )
    db_session.flush()


class TestDeletion:
    def test_an_unused_scenario_deletes(self, api_client: TestClient) -> None:
        _, scenario_id = _scenario(api_client)
        assert api_client.delete(f"/api/v1/scenarios/{scenario_id}").status_code == 204
        assert api_client.get(f"/api/v1/scenarios/{scenario_id}").status_code == 404

    def test_a_scenario_with_recorded_runs_is_a_409_naming_archival(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite_id, scenario_id = _scenario(api_client)
        _record_a_run(db_session, suite_id, scenario_id)
        response = api_client.delete(f"/api/v1/scenarios/{scenario_id}")
        assert response.status_code == 409, response.text
        assert "1 recorded run" in response.text and "Archive it instead" in response.text
        assert api_client.get(f"/api/v1/scenarios/{scenario_id}").status_code == 200


class TestArchival:
    def test_archiving_hides_it_from_listings_but_not_from_a_direct_read(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite_id, scenario_id = _scenario(api_client)
        _record_a_run(db_session, suite_id, scenario_id)
        archived = api_client.post(f"/api/v1/scenarios/{scenario_id}/archive")
        assert archived.status_code == 200 and archived.json()["archived_at"] is not None

        listed = api_client.get(f"/api/v1/suites/{suite_id}/scenarios").json()
        assert listed["total"] == 0 and listed["items"] == []
        searched = api_client.get("/api/v1/scenarios", params={"suite_id": suite_id}).json()
        assert searched["total"] == 0
        everything = api_client.get(
            f"/api/v1/suites/{suite_id}/scenarios", params={"include_archived": True}
        ).json()
        assert [s["id"] for s in everything["items"]] == [scenario_id]
        assert api_client.get(f"/api/v1/scenarios/{scenario_id}").status_code == 200

    def test_an_archived_scenario_cannot_start_a_new_run(self, api_client: TestClient) -> None:
        suite_id, scenario_id = _scenario(api_client)
        api_client.post(f"/api/v1/scenarios/{scenario_id}/archive")
        refused = api_client.post(
            "/api/v1/test-runs",
            json={"suite_id": suite_id, "scenario_id": scenario_id, "mode": "offline_simulation"},
        )
        assert refused.status_code == 409 and "archived" in refused.text

    def test_restore_undoes_archival_and_both_are_idempotent(self, api_client: TestClient) -> None:
        suite_id, scenario_id = _scenario(api_client)
        for _ in range(2):
            assert api_client.post(f"/api/v1/scenarios/{scenario_id}/archive").status_code == 200
        for _ in range(2):
            restored = api_client.post(f"/api/v1/scenarios/{scenario_id}/restore")
            assert restored.status_code == 200 and restored.json()["archived_at"] is None
        listed = api_client.get(f"/api/v1/suites/{suite_id}/scenarios").json()
        assert [s["id"] for s in listed["items"]] == [scenario_id]
