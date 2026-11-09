"""Set up and execute the BhashaBench demonstration run.

Two subcommands, both idempotent and both read-only with respect to anything
they did not create:

    python scripts/demo.py setup   # load the demo scenario, print its ids
    python scripts/demo.py run     # create and execute one run, print evidence

**This script deletes nothing.** It creates a suite and a scenario if they are
absent and reuses them if they are present. It never drops a database, never
removes a run, and never writes to `.env`.

**It calls no paid API.** It drives the local API only, and the demonstration
is configured with the offline `fake` speech and transcription providers, so
no Gnani request is made and no credit is consumed. Setting
`TRANSCRIPTION_PROVIDER`/`SPEECH_PROVIDER` to a live provider would change
that - deliberately, and not by running this.

Requires the backend to be running and `PIPELINE_FIXTURE_AUDIO_PATH` to be set
for `run`; see docs/COMPETITION_DEMO_SCRIPT.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "demo" / "tamil_crop_insurance.yaml"
SCENARIO_NAME = "tamil_crop_insurance"
SUITE_NAME = "Demo suite"
SUITE_DESCRIPTION = "Scenarios used for the recorded demonstration."
DEFAULT_API = "http://localhost:8000"
MODE = "audio_fixture_test"


def _request(api: str, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{api}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} failed with HTTP {exc.code}:\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"cannot reach the API at {api} ({exc.reason}). Start the backend first - "
            "see the Demo section of README.md."
        ) from exc


def _health(api: str) -> None:
    health = _request(api, "/api/v1/health")
    components = {c["name"]: c["status"] for c in health.get("components", [])}
    print(f"API         : {health.get('status')} (env {health.get('environment')})")
    print(f"database    : {components.get('database')}")
    if components.get("database") != "ok":
        raise SystemExit(
            "the database is not reachable, and the run endpoints need it. "
            "Start PostgreSQL (docker compose up -d db) and check that "
            "DATABASE_URL's port matches POSTGRES_HOST_PORT."
        )


def _find_suite(api: str) -> str | None:
    page = _request(api, "/api/v1/suites?limit=100")
    for suite in page.get("items", []):
        if suite.get("name") == SUITE_NAME:
            return str(suite["id"])
    return None


def _find_scenario(api: str, suite_id: str) -> str | None:
    page = _request(api, f"/api/v1/suites/{suite_id}/scenarios?limit=100")
    for scenario in page.get("items", []):
        if scenario.get("name") == SCENARIO_NAME:
            return str(scenario["id"])
    return None


def setup(api: str) -> tuple[str, str]:
    """Ensure the demo suite and scenario exist. Reuses whatever is there."""
    _health(api)

    suite_id = _find_suite(api)
    if suite_id is None:
        suite_id = str(
            _request(
                api,
                "/api/v1/suites",
                method="POST",
                body={"name": SUITE_NAME, "description": SUITE_DESCRIPTION},
            )["id"]
        )
        print(f"suite       : created {suite_id}")
    else:
        print(f"suite       : reused  {suite_id}")

    scenario_id = _find_scenario(api, suite_id)
    if scenario_id is None:
        if not SCENARIO_PATH.is_file():
            raise SystemExit(f"demo scenario missing: {SCENARIO_PATH}")
        scenario_id = str(
            _request(
                api,
                f"/api/v1/suites/{suite_id}/scenarios",
                method="POST",
                body={"yaml": SCENARIO_PATH.read_text(encoding="utf-8")},
            )["id"]
        )
        print(f"scenario    : created {scenario_id}  ({SCENARIO_NAME}, ta-IN)")
    else:
        print(f"scenario    : reused  {scenario_id}  ({SCENARIO_NAME}, ta-IN)")

    return suite_id, scenario_id


def run(api: str) -> None:
    """Create and execute one demonstration run, then print its evidence."""
    suite_id, scenario_id = setup(api)

    created = _request(
        api,
        "/api/v1/test-runs",
        method="POST",
        body={"suite_id": suite_id, "scenario_id": scenario_id, "mode": MODE},
    )
    run_id = created["run_id"]
    print(f"run         : {run_id}  (mode {MODE})")
    print("executing...")

    report = _request(api, f"/api/v1/test-runs/{run_id}/start", method="POST")

    if report.get("status") == "failed" and "no reply for turn 0" in (report.get("error") or ""):
        raise SystemExit(
            "The scripted adapter had no fixture audio, so the run failed on turn 0.\n"
            "Set PIPELINE_FIXTURE_AUDIO_PATH before starting the backend - see the\n"
            "Demo section of README.md - then run this again."
        )

    print()
    print("--- what the run recorded -------------------------------------")
    for field in (
        "status",
        "outcome",
        "mode",
        "bot_adapter",
        "stt_provider",
        "tts_provider",
        "caller_turns",
        "bot_turns",
        "bot_transcripts_succeeded",
        "bot_transcripts_failed",
        "goal_achieved",
        "bot_audio_externally_received",
        "uses_language_model",
        "noise_profile",
        "degradation_seed",
        "total_audio_seconds",
    ):
        print(f"  {field:30} {report.get(field)!r}")

    artefacts = _request(api, f"/api/v1/test-runs/{run_id}/artifacts")
    stored = artefacts.get("artifacts") or artefacts.get("artefacts") or []
    print(f"  {'audio artefacts stored':30} {len(stored)}")

    print()
    print("--- read it in the workspace ----------------------------------")
    print(f"  http://localhost:3000/app/runs/{run_id}")
    print()
    print("Note: the speech and transcription providers are the offline fakes,")
    print("so the bot transcript is scripted stub output and no recognition")
    print("accuracy is measured or claimed. The bot is fixture audio, which is")
    print("why bot_audio_externally_received is false.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "run"))
    parser.add_argument(
        "--api",
        default=DEFAULT_API,
        help=f"base URL of the backend (default {DEFAULT_API})",
    )
    args = parser.parse_args()

    if args.command == "setup":
        setup(args.api)
    else:
        run(args.api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
