# Contributing to BhashaBench

Thanks for working on BhashaBench. This document covers how the repository is
organised, how to get set up, and what a change needs to satisfy before it
merges.

---

## Before you start

BhashaBench is built in [15 controlled phases](docs/DEVELOPMENT_ROADMAP.md),
and **the current phase boundary is enforced**. A change that
implements functionality belonging to a future phase will be asked to split,
even if the code is good. The reason is reviewability: each phase is meant to
be verifiable on its own.

Two rules matter more than anything else here:

1. **Never claim something works when it does not.** If a subsystem is not
   implemented, report it as `degraded`, `unavailable` or `planned` with a
   reason — not as `ok`. The `database` component in `/api/v1/health` is the
   reference example: in Phase 1 it reported "not probed" rather than green,
   and Phase 2 replaced that with a real `SELECT 1` so it now reports `ok` or
   `unavailable` based on what it actually finds.
2. **Never commit a secret.** `.env` is git-ignored. Credentials belong in
   your local `.env` or in GitHub Environments, never in a tracked file,
   never in `.env.example`, and never in a log line or health response.

---

## Development setup

```bash
git clone https://github.com/YushBytes/BhashaBench.git
cd BhashaBench

cp .env.example .env                  # PowerShell: Copy-Item .env.example .env
# Set SECRET_KEY and POSTGRES_PASSWORD in .env.

# Backend
python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
source .venv/bin/activate             # macOS / Linux
pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Frontend
cd frontend && npm install && cd ..
```

Or run the whole stack in containers:

```bash
docker compose up --build
```

---

## Branching

**`main` is the only branch.** All work is committed directly on `main`;
feature branches are not used. A `develop` branch existed while Phases 1
and 2 were being built and was removed once both were integrated; the
history it carried is preserved in `main`.

- Start from the latest `main` and keep each commit to one concern.
- Stage explicit paths. Never `git add .` or `git add -A`: local tooling
  directories sit in the working tree and are excluded only locally.
- Commit locally and push only with the owner's explicit approval.
- Never force-push and never rewrite pushed history. Undo a change with
  `git revert`.

---

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body — what changed and why, wrapped at 72 characters>

<footer — issue references, breaking changes>
```

### Types

| Type | Use for |
|------|---------|
| `feat` | New functionality |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `test` | Adding or correcting tests |
| `refactor` | Behaviour-preserving restructuring |
| `perf` | A performance improvement |
| `chore` | Build, tooling, dependencies, configuration |
| `ci` | CI pipeline changes |

### Scopes

`backend`, `frontend`, `api`, `config`, `docker`, `docs`, `repo`, `deps`,
`ci`, or a subsystem name once it exists (`stt`, `tts`, `caller`,
`degradation`, `telephony`, `eval`).

### Rules

- Subject in the imperative mood: "add health probe", not "added" or "adds".
- No full stop at the end of the subject; 72 characters or fewer.
- Explain **why** in the body, not just what — the diff already shows what.
- One logical change per commit. Keep formatting-only churn in its own commit
  so review stays readable.

### Examples

```
feat(api): add scenario validation endpoint

Scenarios were only validated at load time, so an invalid file was not
discovered until a run started. POST /api/v1/scenarios/validate returns
line-level errors, which the dashboard editor can show inline.

Refs #42
```

```
fix(config): reject placeholder SECRET_KEY in staging

The check only covered production, so a staging deployment could run with
the value committed in .env.example.
```

---

## Code standards

### Python

- Ruff is the single source of truth for lint and formatting; its
  configuration lives in `pyproject.toml`. Run `ruff check .` and
  `ruff format .` before pushing.
- Full type annotations on function signatures. `ANN` rules are enabled.
- Docstrings on modules, classes and public functions. Say *why*, not just
  what the name already says.
- Keep layers honest: no business logic in `api/`, no HTTP concerns in
  `services/`.
- 100-character lines, PEP 8 naming.

### TypeScript and React

- No `any`. Prefer `readonly` on props and `interface` for object shapes.
- Server components by default; add `"use client"` only when a component
  genuinely needs browser state.
- Styling through Tailwind utilities and the design tokens in
  `app/globals.css`. Do not introduce raw hex colours in components — add a
  token instead, so the palette stays consistent.
- `npm run lint` and `npm run typecheck` must both pass.

### Both

- No placeholder implementations, stubbed return values or fabricated sample
  data on a path a user can reach.
- No new dependency without a reason in the commit message. Prefer
  the standard library.
- Split files that grow past roughly 300 lines along a real seam.

---

## Testing

Every behavioural change needs a test. A test that cannot fail is worse than
no test: assertions must check real values, never `assert True`.

```bash
pytest                               # backend suite
pytest -k config                     # match by name
ruff check . && ruff format --check .

cd frontend
npm run lint && npm run typecheck && npm run build
```

What to cover:

- **Endpoints** — status code, response shape, and the error path.
- **Configuration** — defaults, environment overrides, and the validation
  failures, since a bad config should fail at boot.
- **Services** — directly, without an HTTP client.
- **Providers** (phases 4+) — against recorded fixtures. **CI must never call
  a paid API or place a real call.**

`filterwarnings = ["error"]` is set in `pyproject.toml`, so a new deprecation
warning fails the suite. Fix the cause rather than widening the filter.

---

## Integrating a change

### Before committing

- [ ] On `main`, up to date with `origin/main`
- [ ] `pytest` passes, with PostgreSQL running (database tests must not skip)
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `npm run lint`, `npm run typecheck` and `npm run build` pass
- [ ] `docker compose config --quiet` passes, if you touched Compose
- [ ] New configuration documented in `.env.example` **and** the README
- [ ] `git diff --cached` reviewed — no secrets, no build artefacts, no
      unrelated hunks
- [ ] Documentation updated if behaviour or setup changed

### The commit

State what changed and why in the body, how it was verified, and which
phase it belongs to. A behaviour change says so explicitly.

### Pushing

- Push to `main` only after the owner approves; CI runs on every push and
  must be green.
- Never force-push, and never rewrite history that has been pushed. Fix a
  mistake with a new commit or a `git revert`.

---

## Documentation

Update documentation in the same commit as the code:

| File | When |
|------|------|
| `README.md` | Setup, commands, endpoints or environment variables change |
| `docs/ARCHITECTURE.md` | A structural decision is made or revised |
| `docs/DEVELOPMENT_ROADMAP.md` | A phase's scope or status changes |
| `.env.example` | Any configuration variable is added or renamed |
| `CONTRIBUTING.md` | The process itself changes |

Keep the phase-status tables in the README and the roadmap in agreement —
they are the first thing a reader checks to find out what actually works.

---

## Reporting problems

Open an issue with the expected behaviour, what actually happened, minimal
reproduction steps, and your environment (OS, Python and Node versions, and
whether you ran via Docker). Redact credentials from any log you paste.

For a suspected security issue, do not open a public issue — contact the
maintainer directly.
