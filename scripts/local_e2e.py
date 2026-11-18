"""End-to-end check of a running local stack (docker-compose.local.yml).

    python scripts/local_e2e.py
    python scripts/local_e2e.py --frontend http://localhost:3000 --backend http://localhost:8000
    python scripts/local_e2e.py --restart   # also restart db and backend mid-way

Drives the whole operator workflow through the real HTTP surface, as a
browser would, and prints PASS or FAIL per check; exits 1 if any failed.
Standard library only, so it runs with any Python 3.10+ on the host.

    sign-up and cookie sign-in through the frontend's own origin, a workspace,
    a project, a suite, a validated scenario, every implemented execution
    mode (offline fixture text, fixture audio with noise, the reference bot
    over HTTP text and over WebSocket voice), a background run followed to
    completion, turns and transcripts, the recording and a signed expiring
    audio link, evaluation, analytics, comparison, JSON and CSV exports,
    members and roles, workspace isolation (runs and analytics), and run
    deletion. With --restart it also restarts the database and backend
    containers (`docker compose restart`) and checks that the run, its
    recording and the signed-in session all survived.

It creates real data - a fresh account per run, named e2e-<random> - and
deletes only the one run it deletes on purpose. Passwords are generated per
run and never printed. It calls nothing outside the two URLs given, so it
cannot reach a paid provider.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCENARIO = REPO / "scenarios" / "demo" / "tamil_crop_insurance.yaml"
FINISHED = {"completed", "failed", "cancelled", "timed_out"}

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  - ' + detail if detail and not ok else ''}")
    return ok


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class Response:
    def __init__(self, status: int, headers: Any, body: bytes) -> None:
        self.status, self.headers, self.body = status, headers, body

    def json(self) -> Any:
        return json.loads(self.body or b"null")


def call(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with _opener.open(request, timeout=120) as response:
            return Response(response.status, response.headers, response.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers, exc.read())


class Api:
    def __init__(self, base: str, token: str | None = None) -> None:
        self.base, self.token = base.rstrip("/"), token

    def __call__(self, method: str, path: str, body: Any = None) -> Response:
        return call(f"{self.base}{path}", method=method, body=body, token=self.token)


def account(backend: str, label: str) -> tuple[str, str, Api]:
    """Sign up a fresh account and return (email, workspace id, signed-in api)."""
    email = f"e2e-{label}-{secrets.token_hex(4)}@example.test"
    password = secrets.token_urlsafe(18)
    anonymous = Api(backend)
    signup = anonymous(
        "POST",
        "/api/v1/auth/signup",
        {
            "email": email,
            "password": password,
            "display_name": f"E2E {label}",
            "workspace_name": f"E2E {label} workspace",
        },
    )
    check(signup.status == 201, f"sign up {label}", f"HTTP {signup.status} {signup.body[:200]!r}")
    login = anonymous(
        "POST",
        "/api/v1/auth/login",
        {"email": email, "password": password, "session_type": "bearer"},
    )
    check(login.status == 200, f"bearer sign-in {label}", f"HTTP {login.status}")
    api = Api(backend, login.json()["token"])
    workspaces = api("GET", "/api/v1/workspaces").json()
    return email, workspaces[0]["id"], api


def wait_for(api: Api, run_id: str, seconds: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        run = api("GET", f"/api/v1/test-runs/{run_id}").json()
        if run["status"] in FINISHED or time.monotonic() > deadline:
            return run
        time.sleep(1)


def run_once(
    api: Api, suite_id: str, scenario_id: str, mode: str, adapter: str, **extra: Any
) -> dict[str, Any] | None:
    created = api(
        "POST",
        "/api/v1/test-runs",
        {
            "suite_id": suite_id,
            "scenario_id": scenario_id,
            "mode": mode,
            "bot_adapter": adapter,
            **extra,
        },
    )
    if not check(
        created.status == 201,
        f"create {mode} run ({adapter})",
        f"HTTP {created.status} {created.body[:300]!r}",
    ):
        return None
    run_id = created.json()["run_id"]
    started = api("POST", f"/api/v1/test-runs/{run_id}/start?background=true")
    check(started.status == 202, f"start {mode} in the background", f"HTTP {started.status}")
    run = wait_for(api, run_id)
    check(
        run["status"] == "completed",
        f"{mode} run completed",
        f"status {run['status']}, error {run.get('error')!r}",
    )
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # 127.0.0.1, not localhost: on Windows, Python tries ::1 first and waits
    # about two seconds per request for it to fail, since the stack listens on
    # IPv4 loopback only. Browsers fall back at once, so localhost is fine there.
    parser.add_argument("--frontend", default="http://127.0.0.1:3000")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="restart the db and backend containers mid-way and check the data survived",
    )
    args = parser.parse_args()
    fe, be = args.frontend.rstrip("/"), args.backend.rstrip("/")

    # 1. The stack is up.
    health = call(f"{be}/api/v1/health")
    statuses = (
        {c["name"]: c["status"] for c in health.json().get("components", [])}
        if health.status == 200
        else {}
    )
    check(
        health.status == 200 and statuses.get("database") == "ok",
        "backend health, database ok",
        str(statuses),
    )
    check(call(f"{be}/docs").status == 200, "API documentation at /docs")
    check(call(f"{fe}/login").status == 200, "frontend serves /login")
    check(call(f"{fe}/api/v1/health").status == 200, "frontend proxies /api/v1 to the backend")
    gated = call(f"{fe}/app")
    check(
        gated.status in (302, 303, 307, 308) and "/login" in (gated.headers.get("Location") or ""),
        "/app redirects to sign-in without a session",
    )
    headers = call(f"{be}/api/v1/languages").headers
    check(
        headers.get("X-Content-Type-Options") == "nosniff"
        and headers.get("X-Frame-Options") == "DENY",
        "security headers present",
    )
    check(call(f"{be}/api/v1/test-runs").status == 401, "private route refuses an anonymous caller")
    check(
        call(f"{be}/api/v1/auth/options").json() == {"signup_enabled": True},
        "sign-up is open on the local stack",
    )

    # 2. Register; sign in through the frontend origin with a cookie, as the browser does.
    email, home_workspace, owner = account(be, "owner")
    # A cookie session needs the account's password, which only account() knew,
    # so make a second account for the cookie path rather than keep it around.
    cookie_email = f"e2e-cookie-{secrets.token_hex(4)}@example.test"
    cookie_password = secrets.token_urlsafe(18)
    Api(be)(
        "POST",
        "/api/v1/auth/signup",
        {
            "email": cookie_email,
            "password": cookie_password,
            "display_name": "E2E cookie",
            "workspace_name": "E2E cookie workspace",
        },
    )
    browser = call(
        f"{fe}/api/v1/auth/login",
        method="POST",
        body={"email": cookie_email, "password": cookie_password},
        headers={"Origin": fe},
    )
    cookie = browser.headers.get("Set-Cookie") or ""
    check(
        browser.status == 200 and "bb_session=" in cookie and "HttpOnly" in cookie,
        "cookie sign-in through the frontend sets an HttpOnly session",
    )
    session_cookie = cookie.split(";", 1)[0]
    page = call(f"{fe}/app", headers={"Cookie": session_cookie})
    check(
        page.status == 200, "the workspace renders for a signed-in browser", f"HTTP {page.status}"
    )
    call(
        f"{fe}/api/v1/auth/logout", method="POST", headers={"Cookie": session_cookie, "Origin": fe}
    )
    check(
        call(f"{fe}/api/v1/auth/me", headers={"Cookie": session_cookie}).status == 401,
        "sign-out ends the cookie session",
    )

    # 3-4. A workspace and a project.
    workspace = owner("POST", "/api/v1/workspaces", {"name": "E2E team"})
    check(workspace.status == 201, "create a workspace", f"HTTP {workspace.status}")
    workspace_id = workspace.json()["id"]
    project = owner(
        "POST", f"/api/v1/workspaces/{workspace_id}/projects", {"name": "Insurance bots"}
    )
    check(project.status == 201, "create a project", f"HTTP {project.status}")
    project_id = project.json()["id"]

    # 5-6. A suite, then a scenario that validated first.
    suite = owner("POST", "/api/v1/suites", {"name": "E2E suite", "project_id": project_id})
    check(suite.status == 201, "create a test suite in the project", f"HTTP {suite.status}")
    suite_id = suite.json()["id"]
    yaml_text = SCENARIO.read_text(encoding="utf-8")
    validation = owner("POST", "/api/v1/scenarios/validate", {"yaml": yaml_text}).json()
    check(
        validation.get("valid") is True,
        "the scenario validates",
        str(validation.get("errors"))[:300],
    )
    scenario = owner("POST", f"/api/v1/suites/{suite_id}/scenarios", {"yaml": yaml_text})
    check(
        scenario.status == 201,
        "create the scenario",
        f"HTTP {scenario.status} {scenario.body[:200]!r}",
    )
    scenario_id = scenario.json()["id"]

    # 8. Adapters: the reference bot is configured for both protocols.
    adapters = {
        a["name"]: a
        for a in owner("GET", "/api/v1/test-runs/bot-adapters/available").json()["adapters"]
    }
    check(
        adapters.get("http", {}).get("available") is True,
        "http adapter (reference bot, text) available",
    )
    check(
        adapters.get("ws_voice", {}).get("available") is True,
        "ws_voice adapter (reference bot, voice) available",
    )

    # 7, 9-10. Every implemented mode, with conditions on the audio run.
    offline = run_once(owner, suite_id, scenario_id, "offline_simulation", "scripted")
    fixture = run_once(
        owner,
        suite_id,
        scenario_id,
        "audio_fixture_test",
        "scripted",
        noise_profile="moderate_background_noise",
        seed=7,
    )
    fixture_again = run_once(
        owner,
        suite_id,
        scenario_id,
        "audio_fixture_test",
        "scripted",
        noise_profile="heavy_background_noise",
        seed=7,
    )
    text_bot = run_once(owner, suite_id, scenario_id, "text_bot_test", "http")
    voice_bot = run_once(owner, suite_id, scenario_id, "external_bot_test", "ws_voice")
    if text_bot:
        check(
            text_bot.get("bot_text_externally_received") is True,
            "text bot run records replies received from the external bot",
        )
    if voice_bot:
        check(
            voice_bot.get("bot_audio_externally_received") is True,
            "voice bot run records audio received from the external bot",
        )
    if fixture:
        check(
            fixture.get("bot_audio_externally_received") is False,
            "fixture run is not labelled as an external bot test",
        )
        check(
            fixture.get("stt_provider") == "fake" and fixture.get("tts_provider") == "fake",
            "fixture run names the offline fake providers",
        )

    # 11-13. Conversations, transcripts and recordings.
    if fixture:
        run_id = fixture["run_id"]
        turns = owner("GET", f"/api/v1/test-runs/{run_id}/turns").json()["turns"]
        check(
            any(t["speaker"] == "caller" and t["text"] for t in turns)
            and any(t["speaker"] == "bot" for t in turns),
            "turns hold caller and bot utterances with transcripts",
            f"{len(turns)} turns",
        )
        recording = owner("GET", f"/api/v1/test-runs/{run_id}/recording").json()
        check(
            recording.get("status") == "stored",
            "the full recording is stored",
            str(recording.get("status")),
        )
        audio = owner("GET", f"/api/v1/test-runs/{run_id}/recording/audio")
        check(
            audio.status == 200 and audio.body[:4] == b"RIFF",
            "the recording plays (WAV bytes)",
            f"HTTP {audio.status}",
        )
        check(
            call(f"{be}/api/v1/test-runs/{run_id}/recording/audio").status == 401,
            "the recording is not reachable without a session",
        )
        link = owner("POST", f"/api/v1/test-runs/{run_id}/audio-links", {"ttl_seconds": 5}).json()
        signed = call(f"{be}{link['url']}")
        check(
            signed.status == 200 and signed.body[:4] == b"RIFF",
            "a signed audio link opens without a session",
        )
        tampered = link["url"][:-2] + ("AA" if not link["url"].endswith("AA") else "BB")
        check(
            call(f"{be}{tampered}").status in (401, 403, 404), "a tampered signed link is refused"
        )
        time.sleep(6)
        check(
            call(f"{be}{link['url']}").status in (401, 403, 404, 410),
            "an expired signed link is refused",
        )

    # 14. Evaluation.
    for run in (fixture, fixture_again):
        if run:
            evaluated = owner("POST", f"/api/v1/test-runs/{run['run_id']}/evaluations")
            check(
                evaluated.status == 201,
                f"evaluate run {run['run_id'][:8]}",
                f"HTTP {evaluated.status} {evaluated.body[:200]!r}",
            )

    # 15-16. Analytics and comparison, from the backend's own data.
    summary = owner("GET", "/api/v1/analytics/summary")
    check(summary.status == 200, "analytics summary", f"HTTP {summary.status}")
    check(owner("GET", "/api/v1/analytics/trend").status == 200, "analytics trend")
    if fixture and fixture_again:
        compared = owner(
            "GET",
            f"/api/v1/analytics/compare?baseline={fixture['run_id']}&candidate={fixture_again['run_id']}",
        )
        check(
            compared.status == 200,
            "compare two evaluated runs",
            f"HTTP {compared.status} {compared.body[:200]!r}",
        )

    # 17. Exports.
    if fixture:
        as_json = owner("GET", f"/api/v1/test-runs/{fixture['run_id']}/export?format=json")
        check(as_json.status == 200 and "turns" in as_json.json(), "export a run as JSON")
        as_csv = owner("GET", f"/api/v1/test-runs/{fixture['run_id']}/export?format=csv")
        check(as_csv.status == 200 and b"," in as_csv.body, "export a run as CSV")
    runs_csv = owner("GET", "/api/v1/analytics/runs.csv")
    check(runs_csv.status == 200 and runs_csv.body.count(b"\n") >= 5, "export every run as CSV")

    # 18. Members, roles and isolation.
    member_email, _, member = account(be, "member")
    _, _, outsider = account(be, "outsider")
    mine = owner("GET", "/api/v1/analytics/summary").json()["overall"]["runs"]
    check(mine >= 5, "the owner's analytics count the owner's runs", f"{mine} runs")
    theirs = outsider("GET", "/api/v1/analytics/summary").json()["overall"]["runs"]
    check(theirs == 0, "an outsider's analytics include no foreign runs", f"{theirs} runs")
    foreign_csv = outsider("GET", "/api/v1/analytics/runs.csv").body.strip().splitlines()
    check(len(foreign_csv) == 1, "an outsider's run export holds only the header row")
    added = owner(
        "POST",
        f"/api/v1/workspaces/{workspace_id}/members",
        {"email": member_email, "role": "viewer"},
    )
    check(
        added.status == 201, "add a member as viewer", f"HTTP {added.status} {added.body[:200]!r}"
    )
    if fixture:
        check(
            member("GET", f"/api/v1/test-runs/{fixture['run_id']}").status == 200,
            "a viewer can read the workspace's run",
        )
        refused = member(
            "POST",
            "/api/v1/test-runs",
            {"suite_id": suite_id, "scenario_id": scenario_id, "mode": "offline_simulation"},
        )
        check(refused.status == 403, "a viewer cannot create a run", f"HTTP {refused.status}")
        check(
            outsider("GET", f"/api/v1/test-runs/{fixture['run_id']}").status == 404,
            "an outsider gets 404, not 403, for a foreign run",
        )
    member_id = next(
        m["user_id"]
        for m in owner("GET", f"/api/v1/workspaces/{workspace_id}/members").json()
        if m["email"] == member_email
    )
    promoted = owner(
        "PATCH", f"/api/v1/workspaces/{workspace_id}/members/{member_id}", {"role": "member"}
    )
    check(promoted.status == 200, "promote the viewer to member", f"HTTP {promoted.status}")
    removed = owner("DELETE", f"/api/v1/workspaces/{workspace_id}/members/{member_id}")
    check(removed.status == 204, "remove the member", f"HTTP {removed.status}")
    if fixture:
        check(
            member("GET", f"/api/v1/test-runs/{fixture['run_id']}").status == 404,
            "a removed member loses access",
        )

    # Persistence across a restart of the database and the backend.
    if args.restart and fixture:
        compose = ["docker", "compose", "-f", str(REPO / "docker-compose.local.yml")]
        restarted = subprocess.run([*compose, "restart", "db", "backend"], capture_output=True)
        check(restarted.returncode == 0, "restart the db and backend containers")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if call(f"{be}/api/v1/health").status == 200:
                    break
            except OSError:
                pass
            time.sleep(2)
        after = owner("GET", f"/api/v1/test-runs/{fixture['run_id']}")
        check(
            after.status == 200 and after.json()["status"] == "completed",
            "after the restart the run and the session survive",
            f"HTTP {after.status}",
        )
        audio = owner("GET", f"/api/v1/test-runs/{fixture['run_id']}/recording/audio")
        check(
            audio.status == 200 and audio.body[:4] == b"RIFF",
            "after the restart the recording still plays",
            f"HTTP {audio.status}",
        )
        evaluations = owner("GET", f"/api/v1/test-runs/{fixture['run_id']}/evaluations")
        check(
            evaluations.status == 200 and bool(evaluations.json()),
            "after the restart the evaluation is still there",
            f"HTTP {evaluations.status}",
        )

    # Delete one run on purpose.
    if offline:
        deleted = owner("DELETE", f"/api/v1/test-runs/{offline['run_id']}")
        check(
            deleted.status == 200,
            "delete a finished run",
            f"HTTP {deleted.status} {deleted.body[:200]!r}",
        )
        check(
            owner("GET", f"/api/v1/test-runs/{offline['run_id']}").status == 404,
            "the deleted run is gone",
        )

    for api in (owner, member, outsider):
        api("POST", "/api/v1/auth/logout")

    failed = [name for ok, name, _ in results if not ok]
    print(
        f"\n{len(results) - len(failed)} passed, {len(failed)} failed "
        f"(account {email}, workspace {home_workspace[:8]})"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
