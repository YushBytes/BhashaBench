# Deployment plan and runbooks (Phase 15)

**Nothing here has been provisioned or bought.** This repository prepares a
deployment; it does not perform one. Every item that costs money is listed
with an indicative price and left for the owner to approve. Prices were
looked up on 2026-11-18 from secondary sources that disagree with each other
in places - **confirm on the provider's own pricing page, including 18% GST,
before paying.**

## Target: one host, Docker Compose

The smallest honest production shape: one Linux VM running
`docker-compose.prod.yml` (PostgreSQL, a one-shot migration, the backend,
the frontend), with a TLS reverse proxy in front. It fits the design's
stated limits - the rate-limit windows, the run concurrency limiter and the
background worker are per process, and the recovery sweep is idempotent -
and it can be moved to managed services later without code changes.

```
internet --443--> reverse proxy (TLS) --127.0.0.1:3000--> frontend --/api/v1--> backend:8000 --> db:5432
                                                                                       \--> /storage (volume)
```

## What costs money

| Item | Needed? | Indicative price | Source |
|------|---------|------------------|--------|
| VM, 2 vCPU / 4 GB (e.g. Hetzner CX22-class) | Yes | about €4–8.4 / month; reports disagree after Hetzner's April 2026 increase | [Hetzner press](https://www.hetzner.com/pressroom/new-cx-plans/), [sota.io](https://sota.io/blog/hetzner-price-increase-managed-eu-paas-alternative-2026), [vpsfor.dev](https://vpsfor.dev/posts/hetzner-cx22-pricing-2026/) |
| *or* VM in India, 1 vCPU / 2 GB (DigitalOcean Basic, Bangalore) | Alternative | about $12 / month (2 vCPU / 2 GB about $18) | [zapro.ai](https://zapro.ai/vendor/digitalocean-pricing/), [vpsproof.com](https://vpsproof.com/blog/digitalocean-pricing) |
| VM backups (provider snapshots) | Recommended | about 20% (weekly) to 30% (daily) of the VM price on DigitalOcean | as above |
| Domain name (.in) | Yes, for TLS on a public name | roughly ₹800–1,000 first year at Indian-facing registrars, renewals around ₹1,000+; promotions lower | [domainoffer.net](https://domainoffer.net/tld/in), [zoutons.com](https://zoutons.com/news/godaddy-in-domain-offer-may-2026) |
| TLS certificate | Yes | ₹0 with Let's Encrypt (Caddy or certbot) | - |
| Off-host backup storage | Recommended | provider object storage, priced per GB stored; not yet chosen | to confirm |
| Gnani Prisma / Timbre usage | Only for real audio runs | per the Gnani contract | owner's account |
| Sarvam LLM caller | Not until live calls are authorised | capped at ₹100 by the ledger when authorised | `app/caller/llm/budget.py` |
| Telephone number and calls | Not possible: no adapter exists | - | docs/TELEPHONY.md |

**Smallest monthly total** for a single public deployment: one VM plus a
domain, roughly the price of a small VM per month plus about ₹80–90 per
month amortised for the domain. Everything else is optional or usage-based.

## Before the first deploy (owner)

1. Choose and pay for the VM and the domain; point an `A` record at the VM.
2. **Rotate the Gnani key** exposed on 2026-11-16, and use only the new one.
3. Create `.env.production` on the host (never committed), from `.env.example`:
   `APP_ENV=production`; `SECRET_KEY` from
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`;
   `POSTGRES_*` and a matching `DATABASE_URL` with a generated password;
   `CORS_ORIGINS=https://<your domain>`; provider keys if real audio runs are
   intended. Production **refuses to start** on the placeholder secret, the
   placeholder database password or a localhost-only CORS list.

## Runbooks

### Deploy or upgrade

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.production build
scripts/backup.sh                                   # before every upgrade
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
curl -fsS https://<domain>/api/v1/health            # through the proxy
```

The `migrate` service runs `alembic upgrade head` once and the backend
starts only after it succeeds. Rolling back code is `git checkout <previous>`
and the same commands; rolling back a migration is `alembic downgrade -1` in
a one-off container, after reading that migration's docstring and taking a
backup: `b588560f044d` refuses to downgrade when two projects share a suite
name, and downgrading `bcf146f6c696` drops `telephony_calls` with its rows.

### TLS reverse proxy (Caddy, free certificates)

```
<domain> {
    reverse_proxy 127.0.0.1:3000
}
```

### Egress filtering (defence in depth)

The API refuses private, loopback, link-local and metadata destinations for
every bot URL, and pins the address it checked into the connection
(`docs/SECURITY.md`, "Outbound requests"). A host firewall rule adds a second,
independent layer: drop new connections from the API container to
`169.254.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12` (except the compose network)
and `192.168.0.0/16`. With `ufw` that is a `DOCKER-USER` chain rule. It is
free, and it is not applied by this repository because it depends on the host.

### First account

```bash
docker compose -f docker-compose.prod.yml exec backend \
    python -m app.cli users create --email you@example.com --workspace my-team
```

### Back up

`scripts/backup.sh` writes `database.dump` (pg_dump custom format),
`artefacts.tar.gz` (the `/storage` volume) and a `MANIFEST` with checksums.
Read-only against the running system. Copy the directory off the host.

### Restore

Stop the backend and frontend, then `scripts/restore.sh <backup-dir> --yes`.
It verifies the checksums first and refuses without `--yes`.

**Rehearsed** with `scripts/rehearse_restore.sh` on 2026-11-18 against the
development database: dump, restore into a scratch database, every one of
14 tables' row counts identical, scratch database dropped. Rehearse again on
the production host after the first backup.

### Rotate a secret

- `SECRET_KEY`: replace in `.env.production`, `up -d`. Signed audio links
  stop working at once (that is the point); sessions are stored server-side
  and survive. **Connected bots' tokens are encrypted with a key derived from
  `SECRET_KEY`**, so after a rotation every integration's check and runs
  answer 409 "the stored token cannot be read"; each workspace re-enters its
  bot's token (Bots -> the integration -> Replace token), which also resets it
  to `unverified` until it is checked again.
- A provider key: replace and restart; nothing is cached.
- A user's sessions: change their password (`POST /auth/password` revokes
  every other session), or deactivate the account.

### Retention

Set `RETENTION_DAYS`, then run on a schedule (cron), dry run first:

```bash
docker compose -f docker-compose.prod.yml exec backend python -m app.cli runs purge
docker compose -f docker-compose.prod.yml exec backend python -m app.cli runs purge --apply
```

### Stuck runs

The server closes runs left in flight every `PIPELINE_RECOVERY_INTERVAL_SECONDS`.
By hand: `python -m app.cli runs recover-stale --older-than 1h` (dry run),
then `--apply`.

## Logs and request ids

Set `LOG_FORMAT=json` in production: every line is one JSON object with
`ts`, `level`, `logger`, `message`, `request_id` and any structured fields,
credentials redacted. Every response carries `X-Request-ID` (the caller's,
when it is safe, otherwise a new one), so a user can quote the id of a
failing request and it can be found in the logs at once.

## Metrics

Set `METRICS_TOKEN` and scrape `GET /metrics` with
`Authorization: Bearer <token>` from inside the host (the backend is not
published; scrape it on the compose network). Counters and gauges are
documented in `backend/app/core/metrics.py`: responses by method and status
class, time spent, 429s, and runs by status. They are per process and reset
on restart. Alert first on: `/health` failing, a rising 5xx class, and runs
accumulating in `running`.

## Load test

`scripts/load_test.py` (no new dependency). Run on 2026-11-18 against one
uvicorn process on the development laptop (Windows, repository on OneDrive,
PostgreSQL in Docker Desktop), rate limits off, 2,000 requests per path at
concurrency 50:

| Path | Throughput | p50 | p95 | p99 | Non-2xx |
|------|-----------|-----|-----|-----|---------|
| `/health` | 990 req/s | 48 ms | 62 ms | 73 ms | 0 |
| `/api/v1/languages` | 659 req/s | 72 ms | 97 ms | 148 ms | 0 |
| `/api/v1/test-runs?limit=20` (authenticated) | 131 req/s | 373 ms | 598 ms | 675 ms | 0 |

These describe that machine, not a server, and are not a capacity claim.
The finding that carries over: **authenticated reads are the bottleneck**.

### Project-scope caching (2026-11-20), measured

Each authenticated request used to spend three statements on identity and
scope (session row, user row, project roles), and a detail route three more
re-resolving one project and membership. Now the session and user are one
joined statement, and the caller's project roles are read once per request
and kept in that request's own database session (`access_service`, cleared on
any change to a project or membership and on every commit and rollback, never
shared across requests or users; `tests/test_scope_cache.py`). The listing
went from 6 statements to 5, and a run's detail and report routes from 11 to 9.

Re-measured on the same laptop, same path, 2,000 requests at concurrency 50,
one uvicorn process:

| | Runs | Throughput | p50 |
|-|------|-----------|-----|
| Before | 2 | 102 and 111 req/s | 457 and 440 ms |
| After | 4 (one outlier at 73 req/s excluded) | 106, 106, 107, 106 req/s | about 466 ms |
| After, `--workers 4` | 1 warm run | 263 req/s | 228 ms |

**The statement savings did not move throughput.** Fewer round trips is less
database work, but a single process was never waiting on the database: it is
bound by per-request Python work (about 9 ms under the GIL). Throughput scales
with processes, which the production image already exposes as
`UVICORN_WORKERS` (default 1).

### Choosing `UVICORN_WORKERS`

| Environment | Workers | Why |
|-------------|---------|-----|
| Development (`docker-compose.yml`, `--reload`) | 1 | Reload needs a single process |
| Local stack (`docker-compose.local.yml`) | 1 | One user; the image default |
| Planned VM, 2 vCPU / 4 GB | **2** | One per core. PostgreSQL and the Next.js server share the same two cores, so more workers would oversubscribe them |
| Larger VM, N vCPU, nothing else on it | N | Re-run `scripts/load_test.py` on it first |

Measured on the local stack (2026-11-20): a backend worker uses about 100 MB
idle and the frontend about 380 MB, so the production compose file caps the
backend at 1 GB and the frontend at 768 MB.

What multiplies with workers, stated: `RATE_LIMIT_REQUESTS_PER_MINUTE`,
`RATE_LIMIT_LOGINS_PER_MINUTE` and `PIPELINE_MAX_CONCURRENT_RUNS` are enforced
per process, so two workers allow twice each (halve them if the totals
matter). Database connections are at most 15 per worker (pool 5 + overflow
10), far under PostgreSQL's 100. The stale-run sweep runs in every worker but
takes a PostgreSQL advisory lock, so only one sweeps at a time and no run is
abandoned twice (`tests/test_background_runs.py`).

## Not done, and needed for Phase 15's exit criterion

Phase 15 closes only when the platform has **run unattended for a week with
alerting** and a restore has been rehearsed **on the deployment**. Neither
can happen before a host exists. A load test against the deployed host is part of that. Still to do once one
does: external uptime
alerting (a free uptime monitor is enough to start), log shipping, and a
scraper for `/metrics` with alert rules.
