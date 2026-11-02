"""Integration tests for the Phase 3 library, suite and bundle endpoints.

These use `api_client`, whose requests share the test's rolled-back
transaction, so handlers commit normally while nothing persists between tests.
"""

from __future__ import annotations

import uuid

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core import languages
from app.services.bundle import BUNDLE_FORMAT

SCENARIO = """\
name: {name}
language: {language}
persona:
  identity: Caller
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
{extra}"""


def scenario_yaml(name: str, language: str = "hi-IN", extra: str = "") -> str:
    """Build a minimal valid scenario."""
    return SCENARIO.format(name=name, language=language, extra=extra)


def make_suite(client: TestClient, name: str) -> str:
    """Create a suite and return its id."""
    response = client.post("/api/v1/suites", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def make_scenario(client: TestClient, suite_id: str, content: str) -> dict:
    """Create a scenario and return its payload."""
    response = client.post(f"/api/v1/suites/{suite_id}/scenarios", json={"yaml": content})
    assert response.status_code == 201, response.text
    return response.json()


def bundle_of(*names: str, suite: str | None = None) -> str:
    """Build a bundle document from scenario names."""
    document: dict = {"format": BUNDLE_FORMAT}
    if suite:
        document["suite"] = {"name": suite}
    document["scenarios"] = [
        {
            "name": name,
            "language": "hi-IN",
            "persona": {"identity": "Caller"},
            "goal": {"objective": "Ask a question."},
            "expected_outcomes": ["Bot answers"],
        }
        for name in names
    ]
    return yaml.safe_dump(document, sort_keys=False)


class TestLanguageCatalogueEndpoint:
    """`GET /api/v1/languages`."""

    def test_lists_all_thirteen(self, client: TestClient) -> None:
        response = client.get("/api/v1/languages")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 13
        assert len(body["languages"]) == 13

    def test_matches_the_catalogue_exactly(self, client: TestClient) -> None:
        """The endpoint must not drift from the module it serves."""
        body = client.get("/api/v1/languages").json()

        assert [entry["code"] for entry in body["languages"]] == list(languages.SUPPORTED_CODES)

    def test_each_entry_is_complete(self, client: TestClient) -> None:
        first = client.get("/api/v1/languages").json()["languages"][0]

        assert set(first) == {"code", "name", "endonym", "script", "locale"}
        assert all(first.values())

    def test_needs_no_database(self, client: TestClient) -> None:
        """`client` has no database wired in; this must still answer."""
        assert client.get("/api/v1/languages").status_code == 200


class TestScenarioSearch:
    """`GET /api/v1/scenarios`."""

    def test_searches_across_suites(self, api_client: TestClient) -> None:
        first = make_suite(api_client, "Suite one")
        second = make_suite(api_client, "Suite two")
        make_scenario(api_client, first, scenario_yaml("alpha"))
        make_scenario(api_client, second, scenario_yaml("beta"))

        body = api_client.get("/api/v1/scenarios").json()

        assert body["total"] == 2
        assert {item["name"] for item in body["items"]} == {"alpha", "beta"}

    def test_filters_by_suite(self, api_client: TestClient) -> None:
        first = make_suite(api_client, "Owner")
        second = make_suite(api_client, "Other")
        make_scenario(api_client, first, scenario_yaml("mine"))
        make_scenario(api_client, second, scenario_yaml("theirs"))

        body = api_client.get("/api/v1/scenarios", params={"suite_id": first}).json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "mine"

    def test_filters_by_language(self, api_client: TestClient) -> None:
        suite = make_suite(api_client, "Multilingual")
        make_scenario(api_client, suite, scenario_yaml("hindi", "hi-IN"))
        make_scenario(api_client, suite, scenario_yaml("tamil", "ta-IN"))

        body = api_client.get("/api/v1/scenarios", params={"language": "ta-IN"}).json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "tamil"

    def test_filters_by_name_substring_case_insensitively(self, api_client: TestClient) -> None:
        suite = make_suite(api_client, "Named")
        make_scenario(api_client, suite, scenario_yaml("appointment_booking"))
        make_scenario(api_client, suite, scenario_yaml("balance_check"))

        body = api_client.get("/api/v1/scenarios", params={"name": "APPOINT"}).json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "appointment_booking"

    def test_name_filter_treats_wildcards_literally(self, api_client: TestClient) -> None:
        """An unescaped `%` would match everything, which is a silent bug."""
        suite = make_suite(api_client, "Wildcards")
        make_scenario(api_client, suite, scenario_yaml("plain"))

        body = api_client.get("/api/v1/scenarios", params={"name": "%"}).json()

        assert body["total"] == 0

    def test_filters_by_tag(self, api_client: TestClient) -> None:
        suite = make_suite(api_client, "Tagged")
        make_scenario(api_client, suite, scenario_yaml("tagged", extra="tags:\n  - healthcare\n"))
        make_scenario(api_client, suite, scenario_yaml("untagged"))

        body = api_client.get("/api/v1/scenarios", params={"tag": "healthcare"}).json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "tagged"

    def test_multiple_tags_require_all_of_them(self, api_client: TestClient) -> None:
        suite = make_suite(api_client, "Multi-tagged")
        make_scenario(
            api_client,
            suite,
            scenario_yaml("both", extra="tags:\n  - healthcare\n  - smoke\n"),
        )
        make_scenario(api_client, suite, scenario_yaml("one", extra="tags:\n  - healthcare\n"))

        body = api_client.get(
            "/api/v1/scenarios", params=[("tag", "healthcare"), ("tag", "smoke")]
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "both"

    def test_filters_combine_as_and(self, api_client: TestClient) -> None:
        suite = make_suite(api_client, "Combined")
        make_scenario(api_client, suite, scenario_yaml("hindi_tagged", "hi-IN", "tags:\n  - x\n"))
        make_scenario(api_client, suite, scenario_yaml("tamil_tagged", "ta-IN", "tags:\n  - x\n"))

        body = api_client.get("/api/v1/scenarios", params={"language": "hi-IN", "tag": "x"}).json()

        assert body["total"] == 1
        assert body["items"][0]["name"] == "hindi_tagged"

    def test_rejects_an_unsupported_language(self, api_client: TestClient) -> None:
        """A typo should say so, not silently return nothing."""
        response = api_client.get("/api/v1/scenarios", params={"language": "fr-FR"})

        assert response.status_code == 422
        assert "not a supported language" in response.json()["error"]["message"]

    def test_unknown_suite_is_404_not_an_empty_page(self, api_client: TestClient) -> None:
        response = api_client.get("/api/v1/scenarios", params={"suite_id": str(uuid.uuid4())})

        assert response.status_code == 404

    def test_pagination_is_stable_with_duplicate_names(self, api_client: TestClient) -> None:
        """`name` is unique only per suite, so paging needs the id tiebreaker."""
        first = make_suite(api_client, "Page one")
        second = make_suite(api_client, "Page two")
        for suite in (first, second):
            for index in range(3):
                make_scenario(api_client, suite, scenario_yaml(f"shared_{index}"))

        seen: list[str] = []
        for offset in range(0, 6, 2):
            page = api_client.get("/api/v1/scenarios", params={"limit": 2, "offset": offset}).json()
            seen.extend(item["id"] for item in page["items"])

        assert len(seen) == 6
        assert len(set(seen)) == 6

    def test_total_reflects_the_same_filters_as_the_page(self, api_client: TestClient) -> None:
        """Otherwise a list endpoint reports '1 of 5'."""
        suite = make_suite(api_client, "Totals")
        make_scenario(api_client, suite, scenario_yaml("hindi", "hi-IN"))
        for index in range(4):
            make_scenario(api_client, suite, scenario_yaml(f"tamil_{index}", "ta-IN"))

        body = api_client.get("/api/v1/scenarios", params={"language": "hi-IN", "limit": 1}).json()

        assert body["total"] == 1
        assert len(body["items"]) == 1


class TestSuiteUpdate:
    """`PATCH /api/v1/suites/{id}`."""

    def test_updates_the_name(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Original")

        response = api_client.patch(f"/api/v1/suites/{suite_id}", json={"name": "Renamed"})

        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"

    def test_updates_the_description(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Describable")

        response = api_client.patch(
            f"/api/v1/suites/{suite_id}", json={"description": "Now described."}
        )

        assert response.json()["description"] == "Now described."

    def test_omitting_description_leaves_it_untouched(self, api_client: TestClient) -> None:
        """The data-loss case: a partial update must not erase a description."""
        suite_id = make_suite(api_client, "Keeper")
        api_client.patch(f"/api/v1/suites/{suite_id}", json={"description": "Keep me."})

        api_client.patch(f"/api/v1/suites/{suite_id}", json={"name": "Keeper renamed"})

        body = api_client.get(f"/api/v1/suites/{suite_id}").json()
        assert body["description"] == "Keep me."
        assert body["name"] == "Keeper renamed"

    def test_explicit_null_clears_the_description(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Clearable")
        api_client.patch(f"/api/v1/suites/{suite_id}", json={"description": "Remove me."})

        api_client.patch(f"/api/v1/suites/{suite_id}", json={"description": None})

        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["description"] is None

    def test_preserves_scenarios(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "With scenarios")
        make_scenario(api_client, suite_id, scenario_yaml("kept"))

        api_client.patch(f"/api/v1/suites/{suite_id}", json={"name": "Still has them"})

        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["scenario_count"] == 1

    def test_rejects_a_duplicate_name(self, api_client: TestClient) -> None:
        make_suite(api_client, "Taken")
        suite_id = make_suite(api_client, "Mine")

        response = api_client.patch(f"/api/v1/suites/{suite_id}", json={"name": "Taken"})

        assert response.status_code == 409
        assert response.json()["error"]["type"] == "conflict"

    def test_renaming_to_its_own_name_is_allowed(self, api_client: TestClient) -> None:
        """The duplicate check must not trip against the suite itself."""
        suite_id = make_suite(api_client, "Self")

        response = api_client.patch(f"/api/v1/suites/{suite_id}", json={"name": "Self"})

        assert response.status_code == 200

    def test_unknown_suite_is_404(self, api_client: TestClient) -> None:
        response = api_client.patch(f"/api/v1/suites/{uuid.uuid4()}", json={"name": "Ghost"})

        assert response.status_code == 404

    def test_rejects_unknown_fields(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Strict")

        response = api_client.patch(f"/api/v1/suites/{suite_id}", json={"owner": "me"})

        assert response.status_code == 422

    def test_rejects_an_empty_name(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Nonempty")

        assert api_client.patch(f"/api/v1/suites/{suite_id}", json={"name": ""}).status_code == 422


class TestSuiteDelete:
    """`DELETE /api/v1/suites/{id}` - the destructive one."""

    def test_deletes_an_empty_suite(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Empty")

        response = api_client.delete(f"/api/v1/suites/{suite_id}")

        assert response.status_code == 200
        assert response.json()["scenarios_deleted"] == 0
        assert api_client.get(f"/api/v1/suites/{suite_id}").status_code == 404

    def test_refuses_a_suite_containing_scenarios(self, api_client: TestClient) -> None:
        """The database cascades, so the API must not delete silently."""
        suite_id = make_suite(api_client, "Occupied")
        make_scenario(api_client, suite_id, scenario_yaml("protected"))

        response = api_client.delete(f"/api/v1/suites/{suite_id}")

        assert response.status_code == 409
        assert "still contains 1 scenario" in response.json()["error"]["message"]

    def test_refusal_leaves_everything_intact(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Survivor")
        make_scenario(api_client, suite_id, scenario_yaml("survivor"))

        api_client.delete(f"/api/v1/suites/{suite_id}")

        assert api_client.get(f"/api/v1/suites/{suite_id}").status_code == 200
        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["scenario_count"] == 1

    def test_refusal_message_explains_how_to_proceed(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Guided")
        make_scenario(api_client, suite_id, scenario_yaml("guide"))

        message = api_client.delete(f"/api/v1/suites/{suite_id}").json()["error"]["message"]

        assert "cascade=true" in message
        assert "--cascade" not in message

    def test_cascade_deletes_the_suite_and_its_scenarios(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Cascading")
        first = make_scenario(api_client, suite_id, scenario_yaml("one"))
        second = make_scenario(api_client, suite_id, scenario_yaml("two"))

        response = api_client.delete(f"/api/v1/suites/{suite_id}", params={"cascade": "true"})

        assert response.status_code == 200
        assert response.json()["scenarios_deleted"] == 2
        assert api_client.get(f"/api/v1/scenarios/{first['id']}").status_code == 404
        assert api_client.get(f"/api/v1/scenarios/{second['id']}").status_code == 404

    def test_unknown_suite_is_404(self, api_client: TestClient) -> None:
        assert api_client.delete(f"/api/v1/suites/{uuid.uuid4()}").status_code == 404

    def test_malformed_uuid_is_422(self, api_client: TestClient) -> None:
        assert api_client.delete("/api/v1/suites/not-a-uuid").status_code == 422


class TestScenarioCopy:
    """`POST /api/v1/scenarios/{id}/copy`."""

    def test_creates_an_independent_scenario(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Source")
        target_suite = make_suite(api_client, "Target")
        source = make_scenario(api_client, source_suite, scenario_yaml("original"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": target_suite},
        )

        assert response.status_code == 201
        copy = response.json()
        assert copy["id"] != source["id"]
        assert copy["suite_id"] == target_suite
        assert copy["name"] == "original"

    def test_leaves_the_source_untouched(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Untouched source")
        target_suite = make_suite(api_client, "Copy target")
        source = make_scenario(api_client, source_suite, scenario_yaml("stays"))

        api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": target_suite},
        )

        still_there = api_client.get(f"/api/v1/scenarios/{source['id']}").json()
        assert still_there["suite_id"] == source_suite
        assert still_there["name"] == "stays"

    def test_preserves_tags_and_code_mixing(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Rich source")
        target_suite = make_suite(api_client, "Rich target")
        rich = scenario_yaml(
            "rich",
            extra=(
                "tags:\n  - code-mixed\ncode_mixing:\n  secondary:\n    - en-IN\n"
                "  switch_triggers:\n    - numbers\n  secondary_ratio: 0.3\n"
            ),
        )
        source = make_scenario(api_client, source_suite, rich)

        copy = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": target_suite},
        ).json()

        assert copy["spec"]["tags"] == ["code-mixed"]
        assert copy["spec"]["code_mixing"]["secondary"] == ["en-IN"]
        assert copy["spec"]["code_mixing"]["secondary_ratio"] == 0.3

    def test_copies_are_independent_after_the_fact(self, api_client: TestClient) -> None:
        """Updating the copy must not alter the source."""
        source_suite = make_suite(api_client, "Independent source")
        target_suite = make_suite(api_client, "Independent target")
        source = make_scenario(api_client, source_suite, scenario_yaml("shared_name"))
        copy = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": target_suite},
        ).json()

        api_client.put(
            f"/api/v1/scenarios/{copy['id']}",
            json={"yaml": scenario_yaml("shared_name", extra="tags:\n  - changed\n")},
        )

        assert api_client.get(f"/api/v1/scenarios/{source['id']}").json()["spec"]["tags"] == []

    def test_rejects_a_name_clash(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Clash source")
        target_suite = make_suite(api_client, "Clash target")
        source = make_scenario(api_client, source_suite, scenario_yaml("duplicate"))
        make_scenario(api_client, target_suite, scenario_yaml("duplicate"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": target_suite},
        )

        assert response.status_code == 409
        assert "new_name" in response.json()["error"]["message"]

    def test_new_name_resolves_a_clash(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Rename source")
        target_suite = make_suite(api_client, "Rename target")
        source = make_scenario(api_client, source_suite, scenario_yaml("taken"))
        make_scenario(api_client, target_suite, scenario_yaml("taken"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": target_suite, "new_name": "renamed_copy"},
        )

        assert response.status_code == 201
        assert response.json()["name"] == "renamed_copy"
        assert response.json()["spec"]["name"] == "renamed_copy"

    def test_forking_within_the_same_suite_requires_a_new_name(
        self, api_client: TestClient
    ) -> None:
        suite_id = make_suite(api_client, "Fork")
        source = make_scenario(api_client, suite_id, scenario_yaml("forkable"))

        clash = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy", json={"target_suite_id": suite_id}
        )
        forked = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": suite_id, "new_name": "forkable_v2"},
        )

        assert clash.status_code == 409
        assert forked.status_code == 201
        assert forked.json()["suite_id"] == suite_id

    def test_unknown_target_suite_is_404(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Known")
        source = make_scenario(api_client, suite_id, scenario_yaml("source"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/copy",
            json={"target_suite_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    def test_unknown_scenario_is_404(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Target only")

        response = api_client.post(
            f"/api/v1/scenarios/{uuid.uuid4()}/copy", json={"target_suite_id": suite_id}
        )

        assert response.status_code == 404


class TestScenarioMove:
    """`POST /api/v1/scenarios/{id}/move`."""

    def test_preserves_the_scenario_id(self, api_client: TestClient) -> None:
        """Anything already referencing the scenario must stay valid."""
        source_suite = make_suite(api_client, "Move from")
        target_suite = make_suite(api_client, "Move to")
        source = make_scenario(api_client, source_suite, scenario_yaml("mover"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/move",
            json={"target_suite_id": target_suite},
        )

        assert response.status_code == 200
        assert response.json()["id"] == source["id"]
        assert response.json()["suite_id"] == target_suite

    def test_removes_it_from_the_original_suite(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Emptied")
        target_suite = make_suite(api_client, "Filled")
        source = make_scenario(api_client, source_suite, scenario_yaml("leaving"))

        api_client.post(
            f"/api/v1/scenarios/{source['id']}/move",
            json={"target_suite_id": target_suite},
        )

        assert api_client.get(f"/api/v1/suites/{source_suite}").json()["scenario_count"] == 0
        assert api_client.get(f"/api/v1/suites/{target_suite}").json()["scenario_count"] == 1

    def test_moving_to_the_same_suite_is_a_no_op(self, api_client: TestClient) -> None:
        """Keeps a retried request safe."""
        suite_id = make_suite(api_client, "Same")
        source = make_scenario(api_client, suite_id, scenario_yaml("stationary"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/move", json={"target_suite_id": suite_id}
        )

        assert response.status_code == 200
        assert response.json()["id"] == source["id"]

    def test_rejects_a_name_clash(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Move clash source")
        target_suite = make_suite(api_client, "Move clash target")
        source = make_scenario(api_client, source_suite, scenario_yaml("conflicting"))
        make_scenario(api_client, target_suite, scenario_yaml("conflicting"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/move",
            json={"target_suite_id": target_suite},
        )

        assert response.status_code == 409

    def test_failed_move_leaves_the_scenario_where_it_was(self, api_client: TestClient) -> None:
        source_suite = make_suite(api_client, "Rollback source")
        target_suite = make_suite(api_client, "Rollback target")
        source = make_scenario(api_client, source_suite, scenario_yaml("rollback"))
        make_scenario(api_client, target_suite, scenario_yaml("rollback"))

        api_client.post(
            f"/api/v1/scenarios/{source['id']}/move",
            json={"target_suite_id": target_suite},
        )

        assert (
            api_client.get(f"/api/v1/scenarios/{source['id']}").json()["suite_id"] == source_suite
        )

    def test_new_name_renames_the_spec_too(self, api_client: TestClient) -> None:
        """The stored document's own name must not disagree with its row."""
        source_suite = make_suite(api_client, "Rename on move source")
        target_suite = make_suite(api_client, "Rename on move target")
        source = make_scenario(api_client, source_suite, scenario_yaml("before"))

        moved = api_client.post(
            f"/api/v1/scenarios/{source['id']}/move",
            json={"target_suite_id": target_suite, "new_name": "after"},
        ).json()

        assert moved["name"] == "after"
        assert moved["spec"]["name"] == "after"

    def test_unknown_target_suite_is_404(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Move source only")
        source = make_scenario(api_client, suite_id, scenario_yaml("orphan_move"))

        response = api_client.post(
            f"/api/v1/scenarios/{source['id']}/move",
            json={"target_suite_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404


class TestBundleImport:
    """`POST /api/v1/suites/{id}/scenarios/import`."""

    def test_imports_every_entry(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Import target")

        response = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": bundle_of("one", "two", "three")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["imported"] == 3
        assert body["failed"] == 0
        assert body["committed"] is True
        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["scenario_count"] == 3

    def test_dry_run_writes_nothing(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Dry run")

        body = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": bundle_of("a", "b"), "dry_run": True},
        ).json()

        assert body["valid"] == 2
        assert body["imported"] == 0
        assert body["committed"] is False
        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["scenario_count"] == 0

    def test_atomic_import_abandons_everything_on_one_bad_entry(
        self, api_client: TestClient
    ) -> None:
        suite_id = make_suite(api_client, "Atomic")
        bundle = yaml.safe_dump(
            {
                "format": BUNDLE_FORMAT,
                "scenarios": [
                    {
                        "name": "good",
                        "language": "hi-IN",
                        "persona": {"identity": "Caller"},
                        "goal": {"objective": "Ask."},
                        "expected_outcomes": ["Answer"],
                    },
                    {
                        "name": "bad",
                        "language": "fr-FR",
                        "persona": {"identity": "Caller"},
                        "goal": {"objective": "Ask."},
                        "expected_outcomes": ["Answer"],
                    },
                ],
            },
            sort_keys=False,
        )

        body = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import", json={"yaml": bundle}
        ).json()

        assert body["valid"] == 1
        assert body["imported"] == 0
        assert body["committed"] is False
        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["scenario_count"] == 0

    def test_non_atomic_import_keeps_the_valid_entries(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Non-atomic")
        bundle = yaml.safe_dump(
            {
                "format": BUNDLE_FORMAT,
                "scenarios": [
                    {
                        "name": "keeper",
                        "language": "hi-IN",
                        "persona": {"identity": "Caller"},
                        "goal": {"objective": "Ask."},
                        "expected_outcomes": ["Answer"],
                    },
                    {
                        "name": "dropped",
                        "language": "fr-FR",
                        "persona": {"identity": "Caller"},
                        "goal": {"objective": "Ask."},
                        "expected_outcomes": ["Answer"],
                    },
                ],
            },
            sort_keys=False,
        )

        body = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": bundle, "atomic": False},
        ).json()

        assert body["imported"] == 1
        assert body["committed"] is True
        assert api_client.get(f"/api/v1/suites/{suite_id}").json()["scenario_count"] == 1

    def test_reports_validation_errors_per_entry(self, api_client: TestClient) -> None:
        """Never silently skipped."""
        suite_id = make_suite(api_client, "Reported")
        bundle = yaml.safe_dump(
            {
                "format": BUNDLE_FORMAT,
                "scenarios": [
                    {
                        "name": "broken",
                        "language": "fr-FR",
                        "persona": {"identity": "Caller"},
                        "goal": {"objective": "Ask."},
                        "expected_outcomes": ["Answer"],
                    }
                ],
            },
            sort_keys=False,
        )

        body = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import", json={"yaml": bundle}
        ).json()

        assert body["entry_errors"][0]["index"] == 0
        assert body["entry_errors"][0]["name"] == "broken"
        assert any(error["field"] == "language" for error in body["entry_errors"][0]["errors"])

    def test_duplicates_are_reported_never_overwritten(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Duplicates")
        make_scenario(
            api_client, suite_id, scenario_yaml("existing", extra="tags:\n  - original\n")
        )

        body = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": bundle_of("existing")},
        ).json()

        assert body["duplicates"] == ["existing"]
        assert body["imported"] == 0
        # The original must be intact, not replaced by the bundle's version.
        listing = api_client.get(f"/api/v1/suites/{suite_id}/scenarios").json()
        detail = api_client.get(f"/api/v1/scenarios/{listing['items'][0]['id']}").json()
        assert detail["spec"]["tags"] == ["original"]

    def test_rejects_a_non_bundle_document(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Not a bundle")

        response = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": scenario_yaml("single")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["type"] == "yaml_syntax_error"

    def test_rejects_unsafe_yaml(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Unsafe import")

        response = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": "format: !!python/object/apply:os.system ['x']\n"},
        )

        assert response.status_code == 422

    def test_rejects_recursive_aliases(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Recursive import")

        response = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": f"format: {BUNDLE_FORMAT}\nscenarios: &s\n  - *s\n"},
        )

        assert response.status_code == 422
        assert "recursive alias" in response.json()["error"]["message"]

    def test_unknown_suite_is_404(self, api_client: TestClient) -> None:
        response = api_client.post(
            f"/api/v1/suites/{uuid.uuid4()}/scenarios/import",
            json={"yaml": bundle_of("x")},
        )

        assert response.status_code == 404

    def test_rejects_an_oversized_bundle(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Oversized import")
        huge = bundle_of("x") + ("# padding\n" * 40_000)

        response = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import", json={"yaml": huge}
        )

        assert response.status_code in (413, 422)

    def test_duplicate_names_inside_the_bundle_are_rejected(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Internal duplicates")

        body = api_client.post(
            f"/api/v1/suites/{suite_id}/scenarios/import",
            json={"yaml": bundle_of("same", "same")},
        ).json()

        assert body["imported"] == 0
        assert len(body["entry_errors"]) == 2


class TestBundleExport:
    """`GET /api/v1/suites/{id}/scenarios/export`."""

    def test_exports_every_scenario(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Exportable")
        make_scenario(api_client, suite_id, scenario_yaml("alpha"))
        make_scenario(api_client, suite_id, scenario_yaml("beta"))

        response = api_client.get(f"/api/v1/suites/{suite_id}/scenarios/export")

        assert response.status_code == 200
        body = response.json()
        assert body["scenario_count"] == 2
        document = yaml.safe_load(body["yaml"])
        assert document["format"] == BUNDLE_FORMAT
        assert [entry["name"] for entry in document["scenarios"]] == ["alpha", "beta"]

    def test_includes_the_suite_name(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "Named export")
        make_scenario(api_client, suite_id, scenario_yaml("x"))

        document = yaml.safe_load(
            api_client.get(f"/api/v1/suites/{suite_id}/scenarios/export").json()["yaml"]
        )

        assert document["suite"]["name"] == "Named export"

    def test_empty_suite_exports_an_empty_list(self, api_client: TestClient) -> None:
        """A legitimate answer, not an error."""
        suite_id = make_suite(api_client, "Empty export")

        body = api_client.get(f"/api/v1/suites/{suite_id}/scenarios/export").json()

        assert body["scenario_count"] == 0
        assert yaml.safe_load(body["yaml"])["scenarios"] == []

    def test_is_deterministic(self, api_client: TestClient) -> None:
        """Two exports must be byte-identical, so diffs show real changes only."""
        suite_id = make_suite(api_client, "Deterministic")
        make_scenario(api_client, suite_id, scenario_yaml("one"))
        make_scenario(api_client, suite_id, scenario_yaml("two"))

        first = api_client.get(f"/api/v1/suites/{suite_id}/scenarios/export").json()["yaml"]
        second = api_client.get(f"/api/v1/suites/{suite_id}/scenarios/export").json()["yaml"]

        assert first == second

    def test_leaks_no_database_fields(self, api_client: TestClient) -> None:
        suite_id = make_suite(api_client, "No leaks")
        make_scenario(api_client, suite_id, scenario_yaml("clean"))

        document = api_client.get(f"/api/v1/suites/{suite_id}/scenarios/export").json()["yaml"]

        for leaked in ("suite_id", "created_at", "updated_at", "spec_version"):
            assert leaked not in document

    def test_unknown_suite_is_404(self, api_client: TestClient) -> None:
        response = api_client.get(f"/api/v1/suites/{uuid.uuid4()}/scenarios/export")

        assert response.status_code == 404


class TestRoundTripThroughTheApi:
    """Export then import must preserve meaning."""

    def test_round_trip_into_a_fresh_suite(self, api_client: TestClient) -> None:
        source = make_suite(api_client, "Round-trip source")
        target = make_suite(api_client, "Round-trip target")
        rich = scenario_yaml(
            "rich",
            extra=(
                "tags:\n  - code-mixed\n  - healthcare\n"
                "code_mixing:\n  secondary:\n    - en-IN\n"
                "  switch_triggers:\n    - numbers\n  secondary_ratio: 0.35\n"
                "  sample_utterances:\n    - Kal ka appointment chahiye at 10 AM\n"
            ),
        )
        make_scenario(api_client, source, rich)
        make_scenario(api_client, source, scenario_yaml("plain", "ta-IN"))

        exported = api_client.get(f"/api/v1/suites/{source}/scenarios/export").json()["yaml"]
        imported = api_client.post(
            f"/api/v1/suites/{target}/scenarios/import", json={"yaml": exported}
        ).json()

        assert imported["imported"] == 2
        re_exported = api_client.get(f"/api/v1/suites/{target}/scenarios/export").json()["yaml"]
        assert yaml.safe_load(exported)["scenarios"] == yaml.safe_load(re_exported)["scenarios"]

    def test_round_trip_preserves_code_mixing_exactly(self, api_client: TestClient) -> None:
        source = make_suite(api_client, "Mixing source")
        target = make_suite(api_client, "Mixing target")
        make_scenario(
            api_client,
            source,
            scenario_yaml(
                "mixed",
                extra="code_mixing:\n  secondary:\n    - en-IN\n  secondary_ratio: 0.4\n",
            ),
        )

        exported = api_client.get(f"/api/v1/suites/{source}/scenarios/export").json()["yaml"]
        api_client.post(f"/api/v1/suites/{target}/scenarios/import", json={"yaml": exported})

        listing = api_client.get(f"/api/v1/suites/{target}/scenarios").json()
        detail = api_client.get(f"/api/v1/scenarios/{listing['items'][0]['id']}").json()
        assert detail["spec"]["code_mixing"]["secondary"] == ["en-IN"]
        assert detail["spec"]["code_mixing"]["secondary_ratio"] == 0.4

    def test_round_trip_preserves_a_quoted_numeric_fact(self, api_client: TestClient) -> None:
        """`0042` must not come back as 42."""
        source = make_suite(api_client, "Fact source")
        target = make_suite(api_client, "Fact target")
        make_scenario(
            api_client,
            source,
            scenario_yaml("facts", extra='known_facts:\n  reference: "0042"\n'),
        )

        exported = api_client.get(f"/api/v1/suites/{source}/scenarios/export").json()["yaml"]
        api_client.post(f"/api/v1/suites/{target}/scenarios/import", json={"yaml": exported})

        listing = api_client.get(f"/api/v1/suites/{target}/scenarios").json()
        detail = api_client.get(f"/api/v1/scenarios/{listing['items'][0]['id']}").json()
        assert detail["spec"]["known_facts"]["reference"] == "0042"


class TestErrorEnvelopeConsistency:
    """Phase 3 failures must use the Phase 1 envelope."""

    @pytest.mark.parametrize(
        ("method", "path", "payload", "expected_status", "expected_type"),
        [
            ("patch", "/api/v1/suites/bad-uuid", {"name": "x"}, 422, "validation_error"),
            ("delete", "/api/v1/suites/bad-uuid", None, 422, "validation_error"),
            ("get", "/api/v1/scenarios?language=fr-FR", None, 422, "validation_error"),
        ],
    )
    def test_envelope_shape(
        self,
        api_client: TestClient,
        method: str,
        path: str,
        payload: dict | None,
        expected_status: int,
        expected_type: str,
    ) -> None:
        kwargs = {"json": payload} if payload else {}
        response = getattr(api_client, method)(path, **kwargs)

        assert response.status_code == expected_status
        body = response.json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"type", "message", "status_code"}

    def test_no_internals_leak_on_a_phase_three_error(self, api_client: TestClient) -> None:
        response = api_client.delete(f"/api/v1/suites/{uuid.uuid4()}")

        text = response.text
        assert "Traceback" not in text
        assert "sqlalchemy" not in text.lower()
        assert "postgresql" not in text.lower()
