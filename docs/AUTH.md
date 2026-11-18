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

## Workspaces, roles and projects

A **workspace** is the tenancy boundary; a **project** groups suites inside
it; a user reaches anything only through a **membership** of its workspace.
There is no global administrator: someone with database access uses the CLI,
which is a different trust boundary.

| Permission | Least role | Covers |
|------------|-----------|--------|
| `view` | viewer | Read suites, scenarios, runs, turns, artefacts, evaluations, reports, members, projects |
| `edit` | member | Create and change suites and scenarios; create, start, drive and cancel runs and conversations; evaluate; record references |
| `delete` | admin | Delete suites and scenarios |
| `manage_projects` | admin | Create, rename and delete projects |
| `manage_members` | admin | Add, change and remove members — an admin only at `member`/`viewer`; only an owner grants, changes or removes `admin` and `owner` |

Rules enforced by the service, not trusted to a client:

- **Not a member is 404, not 403.** A resource in a workspace the caller does
  not belong to answers exactly as if it did not exist, so ids from another
  tenant cannot be probed. A member whose role is too low gets a 403 that
  names the role and the permission.
- **A workspace always keeps an owner.** Demoting or removing the last owner
  is a 409, whoever asks.
- **Anyone may leave** (delete their own membership), subject to that rule.
- **Members are added by the email of an existing account.** There is no
  email invitation, because the application sends no email.
- Creating a workspace makes the caller its owner and gives it a `Default`
  project.

## Enforcement on every route

| Routes | Check |
|--------|-------|
| `/`, `/health`, `/api/v1/health`, `/api/v1/languages`, `/api/v1/evaluation/metrics`, `/auth/login`, `/auth/signup`, `/auth/options` | Public |
| Transcription, speech, scenario validation, error-rate, provider and adapter lists | Authenticated (they hold no tenant data, but spend provider credit or describe configuration) |
| `/suites/{suite_id}...`, `/scenarios/{scenario_id}...`, `/test-runs/{run_id}...`, `/caller/conversations/{conversation_id}...` | A route dependency from `app/api/access.py` resolves the resource to its workspace before the handler runs: `view` to read, `edit` to change or drive, `delete` to delete |
| Lists and aggregates (`GET /suites`, `/scenarios`, `/test-runs`, `/analytics/*`) | Scoped to the caller's visible projects in SQL; a `suite_id` filter naming a suite the caller cannot see is 404, not an empty page |
| `POST /test-runs`, `POST /caller/conversations` | `edit` on the suite, `view` on the scenario, and the scenario must belong to that suite (422 otherwise) |
| Copy and move a scenario | `view` (copy) or `edit` (move) on the source, and `edit` on the destination suite |
| The transcription WebSocket | Authenticated at the handshake (cookie with an `Origin` check, or a bearer header); refused with close code 1008 |

**Suites belong to projects.** `POST /suites` takes `project_id`; it may be
omitted only when the caller can edit exactly one project (422 otherwise),
because a suite created in the wrong workspace is visible to the wrong
people. Suite names are unique per project. A project holding suites cannot
be deleted (409).

**Pre-tenancy data.** Migration `b588560f044d` moves every suite that existed
before tenancy into a `Default` project of a workspace with slug `legacy`,
which has no members. Grant access with
`bhashabench users create --email you@example.com --workspace legacy`.

**The CLI is unscoped.** It holds database credentials, which already grant
everything; it is a different trust boundary from the API, not a client of it.

## Endpoints

| Method | Path | |
|--------|------|-|
| `GET` | `/api/v1/auth/options` | `{"signup_enabled": bool}`, so a sign-in page offers sign-up only where it works |
| `POST` | `/api/v1/auth/signup` | 403 unless `AUTH_ALLOW_SIGNUP`; 201 with the new user |
| `POST` | `/api/v1/auth/login` | 200 with user and expiry; cookie or token per `session_type`; 401 on any failure |
| `POST` | `/api/v1/auth/logout` | 204; revokes this session |
| `GET` | `/api/v1/auth/me` | The user, their workspaces and roles, the session's expiry |
| `POST` | `/api/v1/auth/password` | Changes the password; returns how many other sessions were revoked |
| `GET` | `/api/v1/workspaces` | The caller's workspaces with their role in each |
| `POST` | `/api/v1/workspaces` | 201; the caller becomes owner; a `Default` project is created |
| `GET` | `/api/v1/workspaces/{id}` | One workspace; 404 to a non-member |
| `GET` | `/api/v1/workspaces/{id}/members` | Members and roles (any member) |
| `POST` | `/api/v1/workspaces/{id}/members` | Add an existing account by email (admin or owner, within `can_assign`) |
| `PATCH` | `/api/v1/workspaces/{id}/members/{user_id}` | Change a role; 409 for the last owner |
| `DELETE` | `/api/v1/workspaces/{id}/members/{user_id}` | Remove a member, or leave with your own id; 409 for the last owner |
| `GET` | `/api/v1/workspaces/{id}/projects` | Projects (any member) |
| `POST` | `/api/v1/workspaces/{id}/projects` | 201 (admin or owner); 409 on a duplicate name |
| `GET` | `/api/v1/projects/{id}` | One project; 404 to a non-member |
| `PATCH` | `/api/v1/projects/{id}` | Rename or describe (admin or owner) |
| `DELETE` | `/api/v1/projects/{id}` | Delete an empty project (admin or owner); 409 while it holds suites |
