"""The reference scenario library: the shipped scenarios, offered to a
signed-in user as a starting point and added through the ordinary create."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.scenario_library import SCENARIO_DIR, reference_scenarios
from app.services.scenario_loader import spec_from_yaml

URL = "/api/v1/scenario-library"


def _shipped_keys() -> set[str]:
    files = [*SCENARIO_DIR.glob("*.yaml"), *SCENARIO_DIR.glob("demo/*.yaml")]
    return {p.relative_to(SCENARIO_DIR).with_suffix("").as_posix() for p in files}


class TestScenarioLibrary:
    def test_it_needs_a_session(self, anonymous: TestClient) -> None:
        assert anonymous.get(URL).status_code == 401

    def test_it_lists_every_shipped_scenario_and_no_bundle(self, api_client: TestClient) -> None:
        body = api_client.get(URL).json()
        keys = {entry["key"] for entry in body["scenarios"]}
        assert keys == _shipped_keys()
        assert body["total"] == len(keys) >= 7
        assert "demo/tamil_crop_insurance" in keys
        assert not any(key.startswith("bundles/") for key in keys)

    def test_each_entry_is_the_file_as_shipped_and_validates(self) -> None:
        for entry in reference_scenarios():
            on_disk = (SCENARIO_DIR / f"{entry.key}.yaml").read_text(encoding="utf-8")
            assert entry.yaml == on_disk
            spec = spec_from_yaml(entry.yaml)
            assert (spec.name, spec.language) == (entry.name, entry.language)

    def test_an_entry_adds_to_a_suite_through_the_ordinary_create(
        self, api_client: TestClient
    ) -> None:
        entry = next(
            e for e in api_client.get(URL).json()["scenarios"] if e["key"].startswith("demo/")
        )
        suite = api_client.post("/api/v1/suites", json={"name": "From the library"}).json()
        created = api_client.post(
            f"/api/v1/suites/{suite['id']}/scenarios", json={"yaml": entry["yaml"]}
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == entry["name"]
