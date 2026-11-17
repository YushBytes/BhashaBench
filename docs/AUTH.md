# Authentication and authorisation (Phase 14, part 1)

Code: `backend/app/auth/` (primitives), `backend/app/services/auth_service.py`,
`backend/app/api/deps.py` (`get_principal`), `backend/app/api/v1/auth.py`.

## Accounts

- **Passwords** are hashed with `hashlib.scrypt` at N = 2^17, r = 8, p = 1
  (OWASP's minimum for scrypt) in a self-describing string, so raising the
  cost later still verifies old hashes and a successful login upgrades them.
  Staging and production refuse `AUTH_PASSWORD_HASH_LOG2_N` below 17; tests
  run at 10.
- **Policy** is length, not composition (NIST SP 800-63B): 12 to 1024
  characters, not only whitespace, not the email address.
- **Emails** are stored lower-cased; the database rejects one that is not.
- **The first account** is created with the CLI, because sign-up is off by
  default:

  ```bash
  bhashabench users create --email you@example.com --workspace my-team
  ```

  The password is prompted for (or read with `--password-stdin`), never taken
  as an argument, so it cannot reach shell history or a process listing.
  `AUTH_ALLOW_SIGNUP=true` opens `POST /auth/signup`, which always creates a
  new workspace owned by the new user.

## Sessions

- A session token is 256 random bits, prefixed `bbs_` so secret scanners can
  recognise a leak. **Only its SHA-256 is stored.**
- **Absolute lifetime** `AUTH_SESSION_TTL_HOURS` (12) is never extended by
  activity; **idle timeout** `AUTH_SESSION_IDLE_MINUTES` (60). `last_seen_at`
  is written at most once a minute, so reads do not become writes.
- **Logout** revokes the session server-side and clears the cookie. A
  **password change** revokes every other session of the user. A
  **deactivated** user's sessions stop working at once.

Two ways to present a session, chosen at login with `session_type`:

| `session_type` | For | What happens |
|----------------|-----|--------------|
| `cookie` (default) | Browsers | `bb_session` is set `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age` = lifetime, `Secure` outside development and test. The token is **not** in the response body, so page script cannot read it |
| `bearer` | CLI, scripts, API clients | The token is returned once in the body; send `Authorization: Bearer <token>`. No cookie |

**CSRF.** A cookie-authenticated `POST`/`PUT`/`PATCH`/`DELETE` whose `Origin`
is present and is neither the API's own origin nor in `CORS_ORIGINS` is
refused with 403 (`Origin: null` included). `SameSite=Strict` is the first
layer; this is the second. Bearer requests need neither, because a browser
never attaches a bearer token by itself. The frontend and the API must
therefore be served from the same site (registrable domain) for the cookie
to be sent at all.

## Login failures

Unknown email, wrong password, deactivated account and locked account all
return the **same 401 with the same message**, and an unknown email still
pays for a full scrypt verification, so neither the body nor the timing says
whether an account exists. `AUTH_MAX_FAILED_LOGINS` (10) consecutive
failures lock the account for `AUTH_LOCKOUT_MINUTES` (15), during which even
the right password is refused. The failure counter is committed before the
refusal is raised; otherwise the request's rollback would undo it.

Trade-off, stated: a lockout lets someone who knows an email address keep
that account locked. Per-client rate limiting (Phase 14, part 2) is the
complement.

## Credential hygiene

- Request models hold passwords as `SecretStr`, so they never appear in a
  `repr` or a log line.
- The validation-error handler drops the rejected `input` of any field whose
  name contains `password`, `token` or `secret`, so a 422 never echoes one.
- Tests assert that neither the password nor the token reaches the logs.

## Endpoints

| Method | Path | |
|--------|------|-|
| `POST` | `/api/v1/auth/signup` | 403 unless `AUTH_ALLOW_SIGNUP`; 201 with the new user |
| `POST` | `/api/v1/auth/login` | 200 with user and expiry; cookie or token per `session_type`; 401 on any failure |
| `POST` | `/api/v1/auth/logout` | 204; revokes this session |
| `GET` | `/api/v1/auth/me` | The user, their workspaces and roles, the session's expiry |
| `POST` | `/api/v1/auth/password` | Changes the password; returns how many other sessions were revoked |
