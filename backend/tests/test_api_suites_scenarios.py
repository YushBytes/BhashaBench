"""Tests for the suite and scenario REST endpoints.

These use `api_client`, whose requests share the test's rolled-back
transaction, so handlers commit normally while nothing persists between tests.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.schemas.scenario_spec import SPEC_VERSION

VALID_YAML = """\
name: appointment_booking
description: Test whether a voice bot can book a doctor appointment.
language: hi-IN

persona:
  identity: Working professional
  speaking_style: polite
  traits:
    - impatient

goal:
  objective: Book an appointment for tomorrow.
  max_turns: 15

known_facts:
  patient_name: Rahul
  preferred_time: "10 AM"

expected_outcomes:
  - Confirm appointment date
  - Confirm appointment time

audio:
  noise_profile: clean
  snr_db: 30
"""

MINIMAL_YAML = """\
name: minimal
language: en-IN
persona:
  identity: Caller
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
"""


def create_suite(client: TestClient, name: str = "Test suite") -> dict:
    """Create a suite via the API and return its payload."""
    response = client.post("/api/v1/suites", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def create_scenario(client: TestClient, suite_id: str, content: str = VALID_YAML) -> dict:
    """Create a scenario via the API and return its payload."""
    response = client.post(f"/api/v1/suites/{suite_id}/scenarios", json={"yaml": content})
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateSuite:
    """`POST /api/v1/suites`."""

    def test_creates_and_returns_201(self, api_client: TestClient) -> None:
        response = api_client.post(
            "/api/v1/suites", json={"name": "Hindi flows", "description": "Hindi scenarios."}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Hindi flows"
        assert body["description"] == "Hindi scenarios."
        assert body["scenario_count"] == 0
        assert uuid.UUID(body["id"])
        assert body["created_at"] and body["updated_at"]

    def test_description_is_optional(self, api_client: TestClient) -> None:
        response = api_client.post("/api/v1/suites", json={"name": "No description"})

        assert response.status_code == 201
        assert response.json()["description"] is None

    def test_rejects_duplicate_name_with_409(self, api_client: TestClient) -> None:
        create_suite(api_client, "Duplicated")

        response = api_client.post("/api/v1/suites", json={"name": "Duplicated"})

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["type"] == "conflict"
        assert error["status_code"] == 409
        assert "already exists" in error["message"]

    def test_rejects_empty_name(self, api_client: TestClient) -> None:
        response = api_client.post("/api/v1/suites", json={"name": ""})

        assert response.status_code == 422
        assert response.json()["error"]["type"] == "validation_error"

    def test_rejects_missing_name(self, api_client: TestClient) -> None:
        assert api_client.post("/api/v1/suites", json={}).status_code == 422

    def test_rejects_unknown_field(self, api_client: TestClient) -> None:
        """`extra="forbid"` means a typo is an error, not silently dropped."""
        response = api_client.post("/api/v1/suites", json={"name": "Extra", "unexpected": "value"})

        assert response.status_code == 422


class TestListSuites:
    """`GET /api/v1/suites`."""

    def test_returns_empty_page_when_none_exist(self, api_client: TestClient) -> None:
        response = api_client.get("/api/v1/suites")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["limit"] == 20
        assert body["offset"] == 0

    def test_lists_created_suites(self, api_client: TestClient) -> None:
        create_suite(api_client, "First")
        create_suite(api_client, "Second")

        body = api_client.get("/api/v1/suites").json()

        assert body["total"] == 2
        assert {item["name"] for item in body["items"]} == {"First", "Second"}

    def test_respects_limit_and_offset(self, api_client: TestClient) -> None:
        for index in range(5):
            create_suite(api_client, f"Suite {index}")

        first = api_client.get("/api/v1/suites", params={"limit": 2, "offset": 0}).json()
        second = api_client.get("/api/v1/suites", params={"limit": 2, "offset": 2}).json()

        assert len(first["items"]) == 2
        assert len(second["items"]) == 2
        assert first["total"] == second["total"] == 5
        # Pages must not overlap.
        assert {item["id"] for item in first["items"]}.isdisjoint(
            {item["id"] for item in second["items"]}
        )

    def test_pagination_is_stable_across_pages(self, api_client: TestClient) -> None:
        """Every row must appear exactly once when paging through."""
        for index in range(7):
            create_suite(api_client, f"Stable {index}")

        seen: list[str] = []
        for offset in range(0, 7, 3):
            page = api_client.get("/api/v1/suites", params={"limit": 3, "offset": offset}).json()
            seen.extend(item["id"] for item in page["items"])

        assert len(seen) == 7
        assert len(set(seen)) == 7

    @pytest.mark.parametrize(
        "params", [{"limit": 0}, {"limit": 101}, {"limit": -1}, {"offset": -1}]
    )
    def test_rejects_out_of_range_pagination(self, api_client: TestClient, params: dict) -> None:
        assert api_client.get("/api/v1/suites", params=params).status_code == 422


class TestGetSuite:
    """`GET /api/v1/suites/{suite_id}`."""

    def test_returns_the_suite(self, api_client: TestClient) -> None:
        created = create_suite(api_client, "Retrievable")

        response = api_client.get(f"/api/v1/suites/{created['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_reports_scenario_count(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Counted")
        create_scenario(api_client, suite["id"], VALID_YAML)
        create_scenario(api_client, suite["id"], MINIMAL_YAML)

        assert api_client.get(f"/api/v1/suites/{suite['id']}").json()["scenario_count"] == 2

    def test_unknown_id_returns_404(self, api_client: TestClient) -> None:
        response = api_client.get(f"/api/v1/suites/{uuid.uuid4()}")

        assert response.status_code == 404
        error = response.json()["error"]
        assert error["type"] == "not_found"
        assert "does not exist" in error["message"]

    def test_malformed_uuid_returns_422(self, api_client: TestClient) -> None:
        """A non-UUID path segment is a request error, not a missing resource."""
        response = api_client.get("/api/v1/suites/not-a-uuid")

        assert response.status_code == 422
        assert response.json()["error"]["type"] == "validation_error"


class TestCreateScenario:
    """`POST /api/v1/suites/{suite_id}/scenarios`."""

    def test_creates_from_valid_yaml(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Scenario host")

        response = api_client.post(
            f"/api/v1/suites/{suite['id']}/scenarios", json={"yaml": VALID_YAML}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "appointment_booking"
        assert body["language"] == "hi-IN"
        assert body["suite_id"] == suite["id"]
        # Asserted against the constant rather than a literal: Phase 3 bumped
        # the schema to v2 (adding optional `tags` and `code_mixing`), and a
        # hardcoded number here would have to be chased on every future bump
        # while proving nothing extra.
        assert body["spec_version"] == SPEC_VERSION

    def test_persists_the_normalized_spec(self, api_client: TestClient) -> None:
        """Defaults must be materialised, not left absent."""
        suite = create_suite(api_client, "Normalised")

        spec = create_scenario(api_client, suite["id"], MINIMAL_YAML)["spec"]

        assert spec["goal"]["max_turns"] == 20
        assert spec["audio"]["noise_profile"] == "clean"
        assert spec["audio"]["snr_db"] == 30.0
        assert spec["persona"]["speaking_style"] == "neutral"

    def test_rejects_invalid_yaml_syntax_with_422(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Bad syntax")

        response = api_client.post(
            f"/api/v1/suites/{suite['id']}/scenarios", json={"yaml": "name: [unclosed\n"}
        )

        assert response.status_code == 422
        assert response.json()["error"]["type"] == "yaml_syntax_error"

    def test_rejects_schema_violation_with_422(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Bad schema")

        response = api_client.post(
            f"/api/v1/suites/{suite['id']}/scenarios",
            json={"yaml": MINIMAL_YAML + "audio:\n  snr_db: 999\n"},
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["type"] == "scenario_validation_error"
        # The field path must reach the client, not just a generic message.
        assert "audio.snr_db" in error["message"]

    def test_rejects_duplicate_name_in_same_suite_with_409(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Duplicate scenarios")
        create_scenario(api_client, suite["id"], VALID_YAML)

        response = api_client.post(
            f"/api/v1/suites/{suite['id']}/scenarios", json={"yaml": VALID_YAML}
        )

        assert response.status_code == 409
        assert response.json()["error"]["type"] == "conflict"

    def test_same_name_allowed_in_a_different_suite(self, api_client: TestClient) -> None:
        """Scenario names are unique per suite, not globally."""
        first = create_suite(api_client, "Suite one")
        second = create_suite(api_client, "Suite two")

        create_scenario(api_client, first["id"], VALID_YAML)
        response = api_client.post(
            f"/api/v1/suites/{second['id']}/scenarios", json={"yaml": VALID_YAML}
        )

        assert response.status_code == 201

    def test_unknown_suite_returns_404(self, api_client: TestClient) -> None:
        response = api_client.post(
            f"/api/v1/suites/{uuid.uuid4()}/scenarios", json={"yaml": VALID_YAML}
        )

        assert response.status_code == 404
        assert response.json()["error"]["type"] == "not_found"

    def test_oversized_yaml_returns_422_from_request_validation(
        self, api_client: TestClient
    ) -> None:
        """The schema's length cap rejects it before any parsing happens."""
        suite = create_suite(api_client, "Oversized")
        huge = "# " + ("x" * (256 * 1024 + 10))

        response = api_client.post(f"/api/v1/suites/{suite['id']}/scenarios", json={"yaml": huge})

        assert response.status_code == 422

    def test_rejects_unsafe_yaml(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Unsafe")

        response = api_client.post(
            f"/api/v1/suites/{suite['id']}/scenarios",
            json={"yaml": "name: !!python/object/apply:os.system ['echo pwned']\n"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["type"] == "yaml_syntax_error"


class TestListScenarios:
    """`GET /api/v1/suites/{suite_id}/scenarios`."""

    def test_lists_only_that_suite_s_scenarios(self, api_client: TestClient) -> None:
        first = create_suite(api_client, "Owner")
        second = create_suite(api_client, "Other")
        create_scenario(api_client, first["id"], VALID_YAML)
        create_scenario(api_client, second["id"], MINIMAL_YAML)

        body = api_client.get(f"/api/v1/suites/{first['id']}/scenarios").json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "appointment_booking"

    def test_summaries_omit_the_spec(self, api_client: TestClient) -> None:
        """List responses stay small; the spec is on the detail endpoint."""
        suite = create_suite(api_client, "Summaries")
        create_scenario(api_client, suite["id"], VALID_YAML)

        item = api_client.get(f"/api/v1/suites/{suite['id']}/scenarios").json()["items"][0]

        assert "spec" not in item
        assert item["language"] == "hi-IN"

    def test_empty_suite_returns_empty_page(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Empty")

        body = api_client.get(f"/api/v1/suites/{suite['id']}/scenarios").json()

        assert body["items"] == []
        assert body["total"] == 0

    def test_unknown_suite_returns_404_not_empty_page(self, api_client: TestClient) -> None:
        """An empty page would be indistinguishable from an empty suite."""
        response = api_client.get(f"/api/v1/suites/{uuid.uuid4()}/scenarios")

        assert response.status_code == 404


class TestGetScenario:
    """`GET /api/v1/scenarios/{scenario_id}`."""

    def test_returns_the_full_spec(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Detail")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        response = api_client.get(f"/api/v1/scenarios/{created['id']}")

        assert response.status_code == 200
        body = response.json()
        assert body["spec"]["persona"]["identity"] == "Working professional"
        assert body["spec"]["known_facts"]["patient_name"] == "Rahul"

    def test_unknown_id_returns_404(self, api_client: TestClient) -> None:
        assert api_client.get(f"/api/v1/scenarios/{uuid.uuid4()}").status_code == 404

    def test_malformed_uuid_returns_422(self, api_client: TestClient) -> None:
        assert api_client.get("/api/v1/scenarios/not-a-uuid").status_code == 422


class TestUpdateScenario:
    """`PUT /api/v1/scenarios/{scenario_id}`."""

    def test_replaces_the_definition(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Updatable")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        updated_yaml = VALID_YAML.replace("snr_db: 30", "snr_db: 12").replace(
            "max_turns: 15", "max_turns: 25"
        )
        response = api_client.put(f"/api/v1/scenarios/{created['id']}", json={"yaml": updated_yaml})

        assert response.status_code == 200
        body = response.json()
        assert body["spec"]["audio"]["snr_db"] == 12.0
        assert body["spec"]["goal"]["max_turns"] == 25

    def test_id_is_stable_across_updates(self, api_client: TestClient) -> None:
        """Existing references to the scenario must stay valid."""
        suite = create_suite(api_client, "Stable id")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        updated = api_client.put(
            f"/api/v1/scenarios/{created['id']}",
            json={"yaml": VALID_YAML.replace("snr_db: 30", "snr_db: 20")},
        ).json()

        assert updated["id"] == created["id"]

    def test_allows_rename_to_a_free_name(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Renameable")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        response = api_client.put(
            f"/api/v1/scenarios/{created['id']}",
            json={"yaml": VALID_YAML.replace("name: appointment_booking", "name: renamed_flow")},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "renamed_flow"

    def test_rejects_rename_onto_a_taken_name(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Name clash")
        create_scenario(api_client, suite["id"], VALID_YAML)
        second = create_scenario(api_client, suite["id"], MINIMAL_YAML)

        response = api_client.put(
            f"/api/v1/scenarios/{second['id']}",
            json={"yaml": MINIMAL_YAML.replace("name: minimal", "name: appointment_booking")},
        )

        assert response.status_code == 409

    def test_updating_with_the_same_name_is_allowed(self, api_client: TestClient) -> None:
        """Keeping the name must not trip the duplicate check against itself."""
        suite = create_suite(api_client, "Self name")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        response = api_client.put(f"/api/v1/scenarios/{created['id']}", json={"yaml": VALID_YAML})

        assert response.status_code == 200

    def test_rejects_invalid_yaml(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Bad update")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        response = api_client.put(
            f"/api/v1/scenarios/{created['id']}", json={"yaml": "name: [unclosed\n"}
        )

        assert response.status_code == 422

    def test_failed_update_leaves_the_scenario_unchanged(self, api_client: TestClient) -> None:
        """A rejected write must not partially apply."""
        suite = create_suite(api_client, "Unchanged")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        api_client.put(
            f"/api/v1/scenarios/{created['id']}",
            json={"yaml": MINIMAL_YAML + "audio:\n  snr_db: 999\n"},
        )

        after = api_client.get(f"/api/v1/scenarios/{created['id']}").json()
        assert after["spec"]["audio"]["snr_db"] == 30.0
        assert after["name"] == "appointment_booking"

    def test_unknown_id_returns_404(self, api_client: TestClient) -> None:
        response = api_client.put(f"/api/v1/scenarios/{uuid.uuid4()}", json={"yaml": VALID_YAML})

        assert response.status_code == 404


class TestDeleteScenario:
    """`DELETE /api/v1/scenarios/{scenario_id}`."""

    def test_deletes_and_returns_204(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Deletable")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        response = api_client.delete(f"/api/v1/scenarios/{created['id']}")

        assert response.status_code == 204
        assert not response.content
        assert api_client.get(f"/api/v1/scenarios/{created['id']}").status_code == 404

    def test_decrements_the_suite_count(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Counting")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        api_client.delete(f"/api/v1/scenarios/{created['id']}")

        assert api_client.get(f"/api/v1/suites/{suite['id']}").json()["scenario_count"] == 0

    def test_unknown_id_returns_404(self, api_client: TestClient) -> None:
        assert api_client.delete(f"/api/v1/scenarios/{uuid.uuid4()}").status_code == 404

    def test_deleting_twice_returns_404(self, api_client: TestClient) -> None:
        suite = create_suite(api_client, "Twice")
        created = create_scenario(api_client, suite["id"], VALID_YAML)

        assert api_client.delete(f"/api/v1/scenarios/{created['id']}").status_code == 204
        assert api_client.delete(f"/api/v1/scenarios/{created['id']}").status_code == 404


class TestValidateEndpoint:
    """`POST /api/v1/scenarios/validate`."""

    def test_valid_yaml_returns_200_and_normalized_forms(self, api_client: TestClient) -> None:
        response = api_client.post("/api/v1/scenarios/validate", json={"yaml": VALID_YAML})

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert body["errors"] == []
        assert body["normalized"]["name"] == "appointment_booking"
        assert "name: appointment_booking" in body["normalized_yaml"]

    def test_invalid_schema_returns_200_with_field_errors(self, api_client: TestClient) -> None:
        """200 because validating succeeded; `valid` carries the verdict."""
        response = api_client.post(
            "/api/v1/scenarios/validate",
            json={"yaml": MINIMAL_YAML + "audio:\n  snr_db: 999\n"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["normalized"] is None
        assert body["normalized_yaml"] is None
        assert any(error["field"] == "audio.snr_db" for error in body["errors"])

    def test_syntax_error_returns_200_with_document_error(self, api_client: TestClient) -> None:
        response = api_client.post("/api/v1/scenarios/validate", json={"yaml": "name: [unclosed\n"})

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["errors"][0]["field"] == "<document>"
        assert body["errors"][0]["type"] == "yaml_syntax"

    def test_reports_every_offending_field(self, api_client: TestClient) -> None:
        bad = MINIMAL_YAML.replace("language: en-IN", "language: fr-FR") + (
            "audio:\n  snr_db: 999\n  packet_loss_percent: 80\n"
        )

        body = api_client.post("/api/v1/scenarios/validate", json={"yaml": bad}).json()

        fields = {error["field"] for error in body["errors"]}
        assert {"language", "audio.snr_db", "audio.packet_loss_percent"} <= fields

    def test_unsafe_yaml_is_reported_not_executed(self, api_client: TestClient) -> None:
        body = api_client.post(
            "/api/v1/scenarios/validate",
            json={"yaml": "name: !!python/object/apply:os.system ['echo pwned']\n"},
        ).json()

        assert body["valid"] is False

    def test_empty_yaml_is_reported(self, api_client: TestClient) -> None:
        body = api_client.post("/api/v1/scenarios/validate", json={"yaml": "# nothing\n"}).json()

        assert body["valid"] is False
        assert "empty" in body["errors"][0]["message"]

    def test_persists_nothing(self, api_client: TestClient) -> None:
        """Validation must have no side effects."""
        api_client.post("/api/v1/scenarios/validate", json={"yaml": VALID_YAML})

        assert api_client.get("/api/v1/suites").json()["total"] == 0

    def test_requires_no_suite(self, api_client: TestClient) -> None:
        """The endpoint is usable before any suite exists."""
        assert (
            api_client.post("/api/v1/scenarios/validate", json={"yaml": VALID_YAML}).status_code
            == 200
        )

    def test_round_trip_through_normalized_yaml(self, api_client: TestClient) -> None:
        """The canonical YAML it returns must itself validate."""
        first = api_client.post("/api/v1/scenarios/validate", json={"yaml": VALID_YAML}).json()

        second = api_client.post(
            "/api/v1/scenarios/validate", json={"yaml": first["normalized_yaml"]}
        ).json()

        assert second["valid"] is True
        assert second["normalized"] == first["normalized"]


class TestErrorEnvelope:
    """Every failure must use the Phase 1 envelope shape."""

    @pytest.mark.parametrize(
        ("method", "path", "payload", "expected_status", "expected_type"),
        [
            ("get", "/api/v1/suites/00000000-0000-0000-0000-000000000000", None, 404, "not_found"),
            ("get", "/api/v1/suites/bad-uuid", None, 422, "validation_error"),
            ("post", "/api/v1/suites", {}, 422, "validation_error"),
        ],
    )
    def test_envelope_shape_is_consistent(
        self,
        api_client: TestClient,
        method: str,
        path: str,
        payload: dict | None,
        expected_status: int,
        expected_type: str,
    ) -> None:
        response = getattr(api_client, method)(path, **({"json": payload} if payload else {}))

        assert response.status_code == expected_status
        body = response.json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"type", "message", "status_code"}
        assert body["error"]["type"] == expected_type
        assert body["error"]["status_code"] == expected_status

    def test_no_stack_trace_or_sql_leaks(self, api_client: TestClient) -> None:
        """Internals must never reach the client."""
        response = api_client.get(f"/api/v1/suites/{uuid.uuid4()}")

        text = response.text
        assert "Traceback" not in text
        assert "sqlalchemy" not in text.lower()
        assert "psycopg" not in text.lower()

    def test_error_does_not_leak_the_database_url(self, api_client: TestClient) -> None:
        response = api_client.get(f"/api/v1/scenarios/{uuid.uuid4()}")

        assert "postgresql" not in response.text
        assert "password" not in response.text.lower()


class TestOpenApiSurface:
    """The documented surface must match what is implemented."""

    def test_all_phase_two_paths_are_documented(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]

        assert set(paths) == {
            "/",
            "/health",
            "/api/v1/health",
            "/api/v1/suites",
            "/api/v1/suites/{suite_id}",
            "/api/v1/suites/{suite_id}/scenarios",
            "/api/v1/scenarios/validate",
            "/api/v1/scenarios/{scenario_id}",
        }

    def test_scenario_spec_schema_is_published(self, client: TestClient) -> None:
        """Clients need the spec schema to build an editor against it."""
        schemas = client.get("/openapi.json").json()["components"]["schemas"]

        assert "ScenarioSpec" in schemas
        assert "Persona" in schemas
        assert "AudioConfig" in schemas

    def test_validate_route_is_not_shadowed_by_the_id_route(self, client: TestClient) -> None:
        """`/scenarios/validate` must not be parsed as a scenario id."""
        operations = client.get("/openapi.json").json()["paths"]["/api/v1/scenarios/validate"]

        assert "post" in operations
