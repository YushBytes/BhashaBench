# Submission checklist — Great Indian AI Internship Challenge

**Deadline: 10 November 2026, 23:59 IST.**

Legend: ✅ done and verified · ⬜ needs your action · ❓ needs information only
you have.

---

## 1. Participant details

| Field | Value | State |
|---|---|---|
| Full name | Ayush Rahul Bidwai | ✅ |
| Institution | SRM Institute of Science and Technology | ✅ |
| Registered email | **❓ YOU MUST PROVIDE** — the address registered for the challenge | ❓ |
| Teammate email | **❓ ONLY IF APPLICABLE** — leave blank for an individual entry | ❓ |

> I have not filled either email in. I do not know your registered address, and
> inventing one would put a wrong address on a submission. Add them when you
> fill in the form.

## 2. Deliverables

| Deliverable | Location | State |
|---|---|---|
| GitHub repository | <https://github.com/YushBytes/BhashaBench> | ✅ |
| One-page pitch | `docs/COMPETITION_ONE_PAGE_PITCH.md` | ✅ |
| Demo video script | `docs/COMPETITION_DEMO_SCRIPT.md` | ✅ |
| Demo video URL | **⬜ PENDING UPLOAD** — record from the script, upload, paste the link | ⬜ |
| LinkedIn post draft | `docs/COMPETITION_LINKEDIN_POST.md` | ✅ |
| LinkedIn post URL | **⬜ PENDING PUBLICATION** — not posted; needs your approval | ⬜ |
| Readiness report | `docs/COMPETITION_READINESS_REPORT.md` | ✅ |
| Screenshots | `docs/competition/screenshots/` (9, captured from the running app) | ✅ |

> **Check the handle when you paste it.** It is `YushBytes` — not
> `YoushBytes`, not `YushByte`. A mistyped repository URL in the form reads as
> a dead link to a judge.

## 3. Repository state

| Check | Result | State |
|---|---|---|
| Branch | `main`, no force-push, no rewritten history | ✅ |
| Local `HEAD` equals `origin/main` | verified after the final push | ✅ |
| Working tree clean | apart from pre-existing untracked local tooling (`.agents/`, `.claude/`, `skills-lock.json`) | ✅ |
| No secret committed | `.env` is git-ignored and was never modified | ✅ |
| Repository visibility | **⬜ CONFIRM IT IS PUBLIC** — open the GitHub URL in a private window and check it loads without signing in | ⬜ |
| Links in README resolve | **⬜ CONFIRM** after the video URL is added | ⬜ |

## 4. Demo functionality

| Check | Result | State |
|---|---|---|
| Backend starts and reports healthy | `api`, `configuration`, `database` all `ok` | ✅ |
| Database migrations consistent | `alembic check` — no new upgrade operations | ✅ |
| Frontend serves all routes | `/`, `/app`, `/app/runs`, `/app/runs/[id]`, `/app/new-test`, `/app/scenarios`, `/app/providers` | ✅ |
| Demo scenario loads | `tamil_crop_insurance` validates and imports | ✅ |
| Demo run completes end to end | `completed`, 5 caller turns, 4 transcribed, 12 artefacts | ✅ |
| Audio artefact plays | `HTTP 200`, 8044 bytes, `audio/wav` | ✅ |
| Waveform drawn from real audio | 12 waveforms, 160 measured bars each | ✅ |
| Test suite | 1,999 collected; 1,958 passed, 41 skipped, 0 failed | ✅ |
| Lint, format, types | `ruff check`, `ruff format --check`, `tsc`, `eslint` all clean | ✅ |
| **Rehearse the demo once before recording** | the stack must be started exactly as in the demo script §1 | ⬜ |

## 5. Deployment

| Item | Decision |
|---|---|
| Public deployment | **Not done, and not recommended.** Classified **C — not safe to deploy publicly without additional security work**: no authentication anywhere, unauthenticated `DELETE` on suites and scenarios, recorded conversation audio reachable by run id, and no inbound rate limiting. Full evidence in the readiness report §8. |
| Recommended submission form | GitHub repository + locally recorded demo video. |
| Action required | None. Do not deploy. |

## 6. Before you submit

1. ⬜ Record the video from `docs/COMPETITION_DEMO_SCRIPT.md` (≤ 2:30).
2. ⬜ Upload it; copy the shareable URL.
3. ⬜ Replace the video placeholder in `README.md` and in the LinkedIn draft.
4. ⬜ Commit and push that one change.
5. ⬜ Confirm the repository is public.
6. ⬜ Review and publish the LinkedIn post; copy its URL.
7. ⬜ Fill in the challenge form: name, institution, **your registered email**,
   teammate email if applicable, GitHub URL, video URL, LinkedIn URL.
8. ⬜ Submit before **10 November 2026, 23:59 IST**.

## 7. Submission confirmation

| Item | State |
|---|---|
| Challenge form actually submitted | **⬜ PENDING — not submitted.** I cannot submit a form on your behalf and have not attempted to. |
| Confirmation email received | ⬜ PENDING |

---

**Nothing in this checklist marked ✅ is an estimate.** Each one corresponds to
a command whose output is recorded in `docs/COMPETITION_READINESS_REPORT.md`.
Every ⬜ and ❓ is work that is genuinely still outstanding.
