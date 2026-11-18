# Running BhashaBench locally on Windows

The whole application on your own machine, at zero cost: no server, no
domain, no API credits, no credentials. Five containers on a private Docker
network:

| Service | What it is | Reachable at |
|---------|------------|--------------|
| `frontend` | Next.js web app (production build) | <http://localhost:3000> |
| `backend` | FastAPI API, background run worker, recovery loop | <http://localhost:8000> |
| — API documentation | Swagger UI / ReDoc | <http://localhost:8000/docs> · <http://localhost:8000/redoc> |
| `db` | PostgreSQL 16 | not published; only the containers reach it |
| `migrate` | applies database migrations, then exits | — |
| `reference-bot` | the repository's test bot (text and voice protocols) | not published |

Everything is bound to `127.0.0.1`, so other machines on your network
cannot reach it.

## What is real and what is simulated

Read this before drawing conclusions from a run.

- **Real:** accounts, sessions, workspaces, roles, scenarios, suites, the run
  engine and its background worker, the caller's rule engine, audio
  degradation, storage of every turn's audio and the full recording, signed
  audio links, evaluation, analytics, comparison and exports.
- **Simulated, and labelled on every run:** speech-to-text and text-to-speech
  are the offline `fake` providers (`stt_provider: fake`,
  `tts_provider: fake`). The transcripts are scripted, not recognised. No
  accuracy figure from this stack describes Gnani or any other engine.
- **The bot:** `scripted` runs use fixture audio or text and report
  `bot_audio_externally_received: false`. `text_bot_test` and
  `external_bot_test` talk to `reference-bot`, a real separate process with
  scripted replies. It shows that the platform drives an external bot. It
  says nothing about how well any production bot behaves.
- **Not available:** telephony (`TELEPHONY_TEST` cannot be created; the
  `mock` provider places no call), the Sarvam language-model caller (live
  calls are disabled in code), and Gnani Evon (no published API; see
  `docs/CALLER.md`).

The stack reads **no `.env` file**, so it cannot pick up a provider key and
cannot make a paid request.

## 1. Prerequisites (once)

1. **Windows 10 22H2 or Windows 11**, 8 GB RAM or more, about 6 GB free disk.
2. **Docker Desktop** (free for personal use, education and small
   businesses): <https://www.docker.com/products/docker-desktop/>. Install
   it with the WSL 2 backend (the default), restart if asked, start Docker
   Desktop, and wait until it says *Engine running*.
3. **Git for Windows**: <https://git-scm.com/download/win>.
4. Optional: **Python 3.10+** to run the end-to-end check (`py --version`).

Check in PowerShell:

```powershell
docker version
docker compose version
git --version
```

## 2. Get the code: outside OneDrive

**Do not build from a folder that OneDrive syncs** (for example
`Desktop` or `Documents` when OneDrive backup is on). OneDrive turns files
into cloud placeholders that Docker cannot read, and the build fails with
`invalid file request`. Use a plain folder:

```powershell
New-Item -ItemType Directory -Force C:\dev | Out-Null
Set-Location C:\dev
git clone https://github.com/YushBytes/BhashaBench.git
Set-Location C:\dev\BhashaBench
```

If you already have a copy inside OneDrive, clone a second one here. Do not
move the OneDrive one.

## 3. Start it

```powershell
Set-Location C:\dev\BhashaBench
docker compose -f docker-compose.local.yml up --build -d
```

The first build takes several minutes (it downloads base images and
installs dependencies); later starts take seconds. Watch it come up:

```powershell
docker compose -f docker-compose.local.yml ps
```

It is ready when `backend` and `frontend` show `healthy` and `migrate`
shows `exited (0)`. Then:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health | ConvertTo-Json -Depth 4
Start-Process http://localhost:3000
```

The health response lists the database as `ok`. Speech and transcription
are reported as the offline fakes, and that is expected here.

## 4. First use

1. Open <http://localhost:3000>, choose **Sign in**, then **Create one**.
   Enter your name, email, a password of 12+ characters and a workspace
   name. You are signed in, as owner of a workspace with a *Default*
   project.
2. **Workspace** — create more projects, create another workspace, and add
   members by the email of an account that already exists (each person signs
   up first), as `viewer`, `member`, `admin` or `owner`.
3. **Scenarios** — create a suite (choose its project), then paste a
   scenario's YAML, **Validate**, and **Add to suite**. Ready-made scenarios
   are in `scenarios\` (for example `scenarios\demo\tamil_crop_insurance.yaml`).
   Open one in Notepad and copy it in.
4. **New test** — pick the scenario and the mode:
   - `offline_simulation`: decisions only, no audio (scripted text replies).
   - `audio_fixture_test`: the full audio pipeline with fixture bot audio;
     choose a noise profile and a seed.
   - `text_bot_test`: the reference bot over HTTP.
   - `external_bot_test`: the reference bot over the voice WebSocket
     (`ws_voice`), or `manual` to upload each bot reply yourself.
   The run starts in the background and its page updates live.
5. **Run page** — conversation turns and transcripts, the audio of every
   turn (original and degraded) and the full recording, stage timings,
   **Evaluate**, **Export JSON / CSV**, and **Delete** for admins and owners.
6. **Analytics** and **Compare** — real aggregates of your runs; compare two
   evaluated runs. **Test runs → Export CSV** downloads every run you can see.

## 5. Verify the whole workflow automatically

With the stack running and Python installed:

```powershell
Set-Location C:\dev\BhashaBench
py scripts\local_e2e.py            # about 70 checks, 2-3 minutes
py scripts\local_e2e.py --restart  # also restarts db and backend mid-way
```

It signs up throwaway accounts (`e2e-…@example.test`) and goes through every
step above through the real HTTP surface: all four modes, background
execution, recordings, signed links, evaluation, analytics, comparison,
exports, roles, and workspace isolation of runs and analytics. `--restart`
also restarts the `db` and `backend` containers and checks that the run, its
recording, its evaluation and the signed-in session all survived. It prints
`PASS`/`FAIL` per check and exits non-zero on any failure. It leaves its data
in place, so you can look at it in the UI. Delete it with the reset in
section 9 if you want a clean slate.

To drive the demo scenario yourself from the command line, sign up in the UI
first, then:

```powershell
$env:BHASHABENCH_EMAIL = "you@example.com"
$env:BHASHABENCH_PASSWORD = "<your password>"
py scripts\demo.py setup
py scripts\demo.py run
```

## 6. Stop, restart, update

```powershell
# Stop (data is kept)
docker compose -f docker-compose.local.yml down

# Start again
docker compose -f docker-compose.local.yml up -d

# Restart one service
docker compose -f docker-compose.local.yml restart backend

# Logs (Ctrl+C to stop following)
docker compose -f docker-compose.local.yml logs -f backend

# Update to the latest code
git pull
docker compose -f docker-compose.local.yml up --build -d
```

Migrations run automatically on every start. On an up-to-date database
they change nothing.

## 7. Where the data lives

Two named Docker volumes, which survive `down`, restarts and rebuilds:

| Volume | Holds |
|--------|-------|
| `bhashabench-local_postgres_data` | the database |
| `bhashabench-local_artefacts` | turn audio and full recordings |

```powershell
docker volume ls --filter name=bhashabench-local
```

Recordings are served only to a signed-in member of the run's workspace,
or through a signed link that expires within 15 minutes.

## 8. Backup and restore

Back up the database to a file in the current folder:

```powershell
docker compose -f docker-compose.local.yml exec -T db pg_dump -U bhashabench -d bhashabench --format=custom > bhashabench.dump
```

Back up the audio:

```powershell
docker run --rm -v bhashabench-local_artefacts:/data -v ${PWD}:/backup alpine tar czf /backup/artefacts.tgz -C /data .
```

Restore (this **replaces** the database's contents with the backup's):

```powershell
docker compose -f docker-compose.local.yml stop backend frontend
Get-Content -AsByteStream bhashabench.dump | docker compose -f docker-compose.local.yml exec -T db pg_restore -U bhashabench -d bhashabench --clean --if-exists
docker run --rm -v bhashabench-local_artefacts:/data -v ${PWD}:/backup alpine tar xzf /backup/artefacts.tgz -C /data
docker compose -f docker-compose.local.yml up -d
```

(`-AsByteStream` needs PowerShell 7. In Windows PowerShell 5.1, run the
restore line from Git Bash instead, as
`docker compose -f docker-compose.local.yml exec -T db pg_restore -U bhashabench -d bhashabench --clean --if-exists < bhashabench.dump`.)

## 9. Reset to empty (deletes everything)

This deletes every account, run and recording in the local stack and
cannot be undone. Back up first if you want any of it.

```powershell
docker compose -f docker-compose.local.yml down -v
docker compose -f docker-compose.local.yml up -d
```

## 10. Changing the local passwords (optional)

The database password, signing key and bot token in
`docker-compose.local.yml` are local-only defaults. They protect containers
that nothing outside your machine can reach, so they are not secrets. **Never
reuse them on a server.** To use your own, set them before starting. The
database password takes effect only on a fresh database (after a reset):

```powershell
$env:LOCAL_DB_PASSWORD = "your-own-value"
$env:LOCAL_SECRET_KEY  = "another-long-random-value"
$env:LOCAL_BOT_TOKEN   = "a-token-of-16-or-more-characters"
docker compose -f docker-compose.local.yml up -d
```

Changing `LOCAL_SECRET_KEY` invalidates every outstanding signed audio link.
Sessions are unaffected.

## 11. Different ports

If 3000 or 8000 is taken:

```powershell
$env:FRONTEND_HOST_PORT = "3100"
$env:BACKEND_HOST_PORT  = "8100"
docker compose -f docker-compose.local.yml up -d
```

The browser only ever calls the frontend's own origin, which forwards
`/api/v1` inside the Docker network. The backend refuses a cookie-signed
write from any origin it does not list (protection against cross-site
request forgery), so its allowed origins follow `FRONTEND_HOST_PORT`
automatically: `localhost:<port>` and `127.0.0.1:<port>`. Set the variables
in the same PowerShell window you run `docker compose` from, and every time:
a later `up` without them moves the frontend back to 3000. Then run the
check against the new ports:

```powershell
py scripts\local_e2e.py --frontend http://127.0.0.1:3100 --backend http://127.0.0.1:8100
```

## 12. Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `invalid file request` during build | The folder is synced by OneDrive. Clone to `C:\dev` (section 2). |
| `error during connect` / `cannot find the file specified` | Docker Desktop is not running. Start it and wait for *Engine running*. |
| `port is already allocated` | Another program uses 3000 or 8000. Use section 11, or stop the other program. |
| `backend` stays `starting`/`unhealthy` | `docker compose -f docker-compose.local.yml logs backend migrate`. A failed migration is shown there. |
| Sign-in says the session expired | Sessions end after the idle timeout. Sign in again. |
| A run fails with `no reply for turn 0` | The `scripted` adapter has no fixtures. That happens only outside this stack, which sets them. |
| `text_bot_test` or `ws_voice` shows *Not configured* | The backend did not get the reference-bot settings. Make sure you started `docker-compose.local.yml`, not `docker-compose.yml`. |
| Slow first build | Normal: the base images and dependencies are downloaded once. |

## 13. Running the developer test suites

These need Python 3.12 and Node 22 on the host, and use the development
compose file's database. See `README.md` → *Testing*. In short:

```powershell
Copy-Item .env.example .env        # once; then set the POSTGRES_* values in it
docker compose up -d db
py -m pip install -r backend\requirements-dev.txt
py -m pytest
npm --prefix frontend ci
npm --prefix frontend test
```

## 14. Making it public later

This guide stops at your machine. Exposing it on the internet takes a server,
a domain, TLS, real secrets and `APP_ENV=production`. Production refuses the
fake providers, so it also needs real provider credentials. See
`docs/DEPLOYMENT.md` for the runbook and the priced list.
