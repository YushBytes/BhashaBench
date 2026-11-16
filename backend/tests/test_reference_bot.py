"""The reference text bot, exercised over a real localhost socket."""

from __future__ import annotations

from collections.abc import Iterator

import httpx2
import pytest

from reference_bot.app import PROTOCOL_VERSION, BotConfig, SessionStore, Turn, create_app
from reference_bot.responder import DEFAULT_SCRIPT, ScriptError, load, load_path
from tests.socket_server import serve

TOKEN = "reference-bot-test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


@pytest.fixture
def client(base_url: str) -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=base_url, timeout=5) as c:
        yield c


def _session(client: httpx2.Client) -> str:
    response = client.post("/v1/sessions", json={"language": "en-IN"}, headers=AUTH)
    assert response.status_code == 201
    return response.json()["session_id"]


class TestProtocol:
    def test_health_needs_no_token_and_names_the_protocol(self, client: httpx2.Client) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["protocol"] == PROTOCOL_VERSION

    def test_a_full_conversation(self, client: httpx2.Client) -> None:
        sid = _session(client)
        url = f"/v1/sessions/{sid}/turns"
        first = client.post(
            url,
            json={"text": "Hello, I am calling about my request", "turn_index": 0},
            headers=AUTH,
        )
        assert "reference number" in first.json()["text"]
        second = client.post(url, json={"text": "It is 4 4 7 2 1 9", "turn_index": 1}, headers=AUTH)
        assert second.json()["text"].endswith("reference 447219 is confirmed.")
        third = client.post(url, json={"text": "Thank you", "turn_index": 2}, headers=AUTH)
        assert third.json() == {
            "text": "You are welcome. Goodbye.",
            "end_session": True,
            "turn_index": 2,
        }
        after = client.post(url, json={"text": "Hello?", "turn_index": 3}, headers=AUTH)
        assert after.status_code == 409
        assert after.json()["error"]["code"] == "session_ended"
        assert client.delete(f"/v1/sessions/{sid}", headers=AUTH).status_code == 204
        assert client.delete(f"/v1/sessions/{sid}", headers=AUTH).status_code == 404

    def test_a_repeated_idempotency_key_returns_the_stored_reply_without_advancing(
        self, client: httpx2.Client
    ) -> None:
        sid = _session(client)
        url = f"/v1/sessions/{sid}/turns"
        headers = {**AUTH, "Idempotency-Key": "run-1:turn-0"}
        first = client.post(url, json={"text": "hello", "turn_index": 0}, headers=headers)
        again = client.post(url, json={"text": "hello", "turn_index": 0}, headers=headers)
        assert first.status_code == again.status_code == 200
        assert first.json() == again.json()
        # That the retry did not advance the session is asserted directly
        # against the store in TestSessionStore.

    def test_the_correlation_id_is_echoed(self, client: httpx2.Client) -> None:
        response = client.get("/health", headers={"X-Correlation-ID": "abc-123"})
        assert response.headers["X-Correlation-ID"] == "abc-123"


class TestErrors:
    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Bearer wrong-token-wrong-token"}, {"Authorization": TOKEN}],
    )
    def test_v1_needs_the_exact_bearer_token(
        self, client: httpx2.Client, headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/sessions", json={"language": "en-IN"}, headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert TOKEN not in response.text

    def test_an_unknown_session_is_404(self, client: httpx2.Client) -> None:
        response = client.post(
            "/v1/sessions/nope/turns", json={"text": "x", "turn_index": 0}, headers=AUTH
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "session_not_found"

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"text": "x"},
            {"text": "x", "turn_index": -1},
            {"text": "x" * 4001, "turn_index": 0},
            {"text": "x", "turn_index": 0, "extra": 1},
        ],
    )
    def test_a_malformed_turn_is_422_in_the_envelope(
        self, client: httpx2.Client, body: dict[str, object]
    ) -> None:
        sid = _session(client)
        response = client.post(f"/v1/sessions/{sid}/turns", json=body, headers=AUTH)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_a_short_token_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="16 characters"):
            BotConfig(token="short")


class TestSessionStore:
    def test_capacity_is_bounded(self) -> None:
        store = SessionStore(BotConfig(token=TOKEN, max_sessions=2))
        store.create("en-IN")
        store.create("en-IN")
        with pytest.raises(Exception, match="no free session slots"):
            store.create("en-IN")

    def test_sessions_expire(self) -> None:
        now = [0.0]
        store = SessionStore(BotConfig(token=TOKEN, session_ttl_seconds=10), clock=lambda: now[0])
        sid = store.create("en-IN")
        now[0] = 11.0
        with pytest.raises(Exception, match="no such session"):
            store.turn(sid, Turn(text="hello", turn_index=0), None)

    def test_a_retried_turn_does_not_advance_the_conversation(self) -> None:
        store = SessionStore(BotConfig(token=TOKEN, max_turns_per_session=1))
        sid = store.create("en-IN")
        first = store.turn(sid, Turn(text="hello", turn_index=0), "k")
        assert store.turn(sid, Turn(text="hello", turn_index=0), "k") == first
        # A new key is a new turn, and the one-turn limit is now reached.
        with pytest.raises(Exception, match="turn limit"):
            store.turn(sid, Turn(text="hello", turn_index=1), "k2")


class TestScript:
    def test_the_default_script_is_deterministic(self) -> None:
        assert DEFAULT_SCRIPT.respond("hello") == DEFAULT_SCRIPT.respond("hello")

    def test_indic_digits_are_not_mistaken_for_no_number(self) -> None:
        # NFKC does not fold Devanagari digits, but `\\d` matches them, so the
        # number rule fires and quotes them back.
        reply = DEFAULT_SCRIPT.respond("मेरा नंबर ४४७२१९ है")
        assert "४४७२१९" in reply.text

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            ({}, "'rules' list"),
            ({"rules": []}, "between 1 and"),
            ({"rules": [{"reply": "x", "contains_any": ["a"]}]}, "unconditional"),
            ({"rules": [{"reply": ""}]}, "1-2000"),
            ({"rules": [{"reply": "x", "when": 1}]}, "unknown keys"),
            ({"rules": [{"reply": "x", "has_number": "yes"}]}, "true or false"),
            ({"rules": [{"reply": "x"}], "greeting": ""}, "greeting"),
        ],
    )
    def test_a_bad_script_is_refused_with_a_reason(self, data: dict, message: str) -> None:
        with pytest.raises(ScriptError, match=message):
            load(data)

    def test_a_script_loads_from_json(self, tmp_path) -> None:
        path = tmp_path / "script.json"
        path.write_text(
            '{"rules": [{"reply": "Always this."}], "greeting": "Hi"}', encoding="utf-8"
        )
        script = load_path(path)
        assert script.greeting == "Hi"
        assert script.respond("anything").text == "Always this."

    def test_an_unreadable_script_is_refused(self, tmp_path) -> None:
        with pytest.raises(ScriptError, match="could not read"):
            load_path(tmp_path / "missing.json")
