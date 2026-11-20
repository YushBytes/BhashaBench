# Security

What BhashaBench protects, how, and what is known to be incomplete. Each
control names the module that implements it, so a claim here can be checked
against the code.

## Secrets

- Credentials are read from the environment only. `.env` is git-ignored and
  `.env.example` holds placeholders.
- Every provider credential is a pydantic `SecretStr` (`gnani_api_key`,
  `sarvam_api_key`, and every credential added since), so it is masked in a
  settings repr, a dump and a failing test's assertion diff. It is unwrapped
  only where a client is constructed.
- Offline tests cannot see a credential exported in the developer's shell:
  an autouse fixture in `backend/tests/conftest.py` removes every
  `*_api_key` variable for tests not marked `live`.
- Provider error text is passed through `app/transcription/redaction.py`
  before it reaches the database or an API response.
- Every log line passes through the same redactor, in both formats: the
  JSON formatter redacts each field, the text formatter the whole line
  including the traceback. The wire-level loggers (`websockets`, `httpcore`,
  `hpack`) are held at INFO or above whatever the process level, because at
  DEBUG `websockets` logs each handshake header.

**Finding, 2026-11-19.** The local Docker stack runs at DEBUG in text
format, and its backend log carried the voice bot's
`Authorization: Bearer ...` line from the `websockets` handshake: the text
formatter did not redact, contrary to its own documentation, and the
library logged headers at DEBUG. The token was the local reference bot's
non-secret default, and nothing deployed was affected (production logs at
INFO). Both causes are fixed above, and each has a test.

**Incident, 2026-11-16.** A failing test compared the Gnani key directly and
pytest printed it in a session transcript. Both causes are fixed (above); the
key is treated as compromised and its rotation is the owner's manual task.

## Authentication and authorisation (Phase 14)

Design and rules: [AUTH.md](AUTH.md). In short:

- Every route outside a short public list (liveness, the language and metric
  catalogues, login, sign-up) requires a session; `test_access_control.py`
  sweeps the OpenAPI document to prove it.
- Passwords: stdlib scrypt at N = 2^17 (refused below that when deployed),
  length-based policy, `SecretStr` in request models, never echoed by the
  validation handler.
- Sessions: 256-bit opaque tokens, stored as SHA-256 only; absolute and idle
  expiry; server-side revocation on logout and on password change.
- Browser sessions use an `HttpOnly`, `SameSite=Strict`, `Secure`-when-deployed
  cookie whose token never appears in a response body. Cookie-authenticated
  writes and WebSocket handshakes from a foreign `Origin` are refused.
- Login failures are indistinguishable in body and in timing; ten in a row
  lock the account for fifteen minutes.
- Tenancy: a resource in another workspace is a 404 identical to a missing
  one; the role matrix decides the rest. A run cannot use another suite's
  scenario.

Session tokens carry a `bbs_` prefix, and the shared redactor
(`app/transcription/redaction.py`) removes any `bbs_...` token wherever it
appears - added after the Phase 9 crash test found one surviving in a run's
stored error.

**Rate limits and headers (Phase 14 part 2)**, `app/core/security.py`:
every `/api/` request is limited per client address
(`RATE_LIMIT_REQUESTS_PER_MINUTE`, 600), and login per address *and* per
email (`RATE_LIMIT_LOGINS_PER_MINUTE`, 10), answering 429 with
`Retry-After` and checked before the password is verified. Liveness is never
limited. Every API response carries `nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, a device-denying `Permissions-Policy`, COOP,
and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
(the dev-only docs pages excepted); HSTS is added in staging and production;
auth responses are `no-store`. The frontend sends the same headers except
the CSP.

**Scanning in CI (Phase 14 part 2).** Every push runs:

| Gate | Fails on |
|------|----------|
| `pip-audit -r backend/requirements.txt` | Any known vulnerability in a runtime Python dependency |
| `npm audit --omit=dev --audit-level=high` | A high or critical advisory in a runtime frontend dependency |
| Gitleaks over the full git history (`.gitleaks.toml`) | Any credential-shaped string not on the allowlist |

The gitleaks allowlist names the exact fabricated values the redaction tests
use, never a directory, so a real key pasted into a test still fails the
build. When it was introduced the full history (141 commits) was scanned:
all 11 findings were documented fixtures, and none was a working credential.

Dev-only advisories are reviewed by hand. Open at the time of writing:
`picomatch` (high, under the ESLint toolchain; its only fix is a forced,
breaking upgrade). It is not shipped in any build.

**Known gaps.** The rate-limit windows live in one process, so N processes
allow N times the rate; `TRUST_FORWARDED_FOR` must only be set behind a
proxy that overwrites the header. The frontend has no Content-Security-
Policy yet: Next's inline scripts need per-request nonces, and a policy with
`'unsafe-inline'` would be decoration. No multi-factor authentication. No email verification or password
reset by email: the application sends no email, and an account is created
by an operator (`bhashabench users create`) or by sign-up when enabled.

## Outbound requests (SSRF)

`app/core/outbound.py` guards every request whose destination comes from
configuration rather than from a cited vendor constant - today, the HTTP bot
adapter's base URL and the `ws_voice` adapter's WebSocket URL.

| Rule | Behaviour |
|------|-----------|
| Scheme | `http` or `https` only |
| Userinfo | Refused, and not echoed in the error |
| Allowlist | The host must be listed exactly or under a `*.suffix` wildcard; empty refuses all |
| Addresses | Every resolved address is checked. Link-local, cloud metadata, multicast, reserved and unspecified are always refused; loopback and private ranges need an explicit opt-in |
| IPv4-mapped IPv6 | Judged as the IPv4 address it maps |
| Transport | Plain `http`/`ws` only to a loopback target, or to a private one with `BOT_HTTP_ALLOW_PLAIN_PRIVATE` (the local Docker stack's reference bot). That flag never widens which addresses are reachable, and the settings refuse it when `APP_ENV` is staging or production |
| Redirects | Never followed. The HTTP adapter passes `follow_redirects=False`; the WebSocket adapter overrides `websockets`' redirect handling, which by default follows a 3xx handshake answer cross-origin and resends the bearer token to a URI the guard never saw |
| Pinning | The socket is opened to an address the check approved (`app/core/pinned.py`), never by resolving the name again. HTTP: a network backend that refuses any host or port it was not pinned to. WebSocket: a socket pre-connected to the pinned address, passed as `sock=`; TLS still verifies the certificate against the hostname |
| Proxies | Environment proxies (`HTTPS_PROXY` and friends) are ignored by both clients, because a proxy would resolve the host itself |

**DNS rebinding (closed 2026-11-20).** Before pinning, resolution happened
immediately before each request and again inside the connect, so a hostile
resolver could approve a public address and then answer the connect with
loopback or the metadata service. `tests/test_pinned_transport.py` proves the
fix with a hostname that does not exist in real DNS: the request succeeds only
because the socket goes to the pinned address. Each request (and each retry)
is checked afresh, and connects to what that check approved. Network-level
egress filtering (a firewall that drops traffic to private ranges from the API
container) is still recommended on a deployed host as defence in depth; see
`docs/DEPLOYMENT.md`.
