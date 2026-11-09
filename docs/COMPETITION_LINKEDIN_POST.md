# LinkedIn post — draft

> **Not published.** This is a draft for review. Nothing is posted until you
> approve it and post it yourself.
>
> **Two placeholders to fill before posting:**
>
> 1. `[DEMO VIDEO LINK]` — the URL after you upload the recording.
> 2. **The Gnani AI page tag.** I have not verified Gnani AI's official
>    LinkedIn page, so I have not written a handle: an incorrect `@` mention
>    tags a stranger. Open Gnani AI's official page, then type `@` and select
>    it from LinkedIn's own suggestions so the mention resolves. The same
>    applies to the challenge's hashtag if it has an official one.

---

## Post text

Indian-language voice bots are tested in the wrong conditions.

They get evaluated on clean studio audio, in one language at a time, by someone
listening and deciding it sounded fine. Then a real call arrives: Tamil with
the policy number in English, a market in the background, a mobile network
dropping eight per cent of the packets. The failures show up in production,
where customers find them first.

So for the Great Indian AI Internship Challenge I built **BhashaBench** — an
instrument that tests whether Indian-language voice AI actually understands
people under the conditions they really call in.

How it works: a scenario declares who is calling, in which language, what they
want, and what the line sounds like. The platform then synthesises the caller's
speech with **Gnani Timbre**, degrades it the way a real network does —
band-limiting, background noise at a measured signal-to-noise ratio, clipping,
packet loss, all reproducible from a fixed seed — carries it to the bot under
test, transcribes the reply with **Gnani Prisma**, and decides what the caller
says next. Every turn is stored with its audio, its timings and its state
transitions.

The demo scenario is a paddy farmer near Thanjavur ringing a crop-insurance
helpline about a claim after unseasonal rain. He speaks Tamil, but the policy
number and the amount come out in English — which is exactly where recognition
breaks. The run completed five caller turns, transcribed four bot replies and
stored twelve audio artefacts, keeping both the original and the degraded
version of every turn so the evidence can be reproduced.

Its verdict on that bot was "no progress". That negative result is the point:
the instrument is supposed to find failures, not flatter the system under test.

**What I learned building it**

The hardest engineering in a measurement tool is not the measuring — it is
refusing to report things you have not measured. Three decisions shaped the
whole codebase:

- Optional stays optional. The provider does not report a confidence score, so
  the field is null rather than 1.0. Defaulting it would have read as "the model
  was certain" instead of "this was never measured", and every metric built on
  it would have been fiction.
- Honesty has to be structural, not editorial. Whether audio actually reached an
  external bot is computed from the replies, never from the run's own label — so
  a mislabelled run is visible as one instead of being taken at its word.
- A capability you cannot verify gets named for what it is. Gnani Evon is **not**
  integrated: no text-generation endpoint is published and the released model has
  no hosted inference provider, so the caller is a deterministic rule engine and
  the code says exactly that. Writing a stub that pretended otherwise would have
  been the easy thing and the wrong one.

1,999 automated tests, 1,958 passing and the remaining 41 opt-in because they
spend real API credits. Telephony, automated scoring and authentication are
scoped as later phases and are documented as not built — the README says what
works and what does not.

Code: https://github.com/YushBytes/BhashaBench
Demo: [DEMO VIDEO LINK]

Thanks to [tag Gnani AI's official page here] for setting a problem worth
building an instrument for.

#VoiceAI #SpeechRecognition #IndianLanguages #MachineLearning #Python

---

## Notes on claims in this post

Every factual statement above is supported by the repository:

| Claim | Evidence |
|---|---|
| Timbre and Prisma integrated | `app/speech/providers/timbre.py`, `app/transcription/providers/prisma.py`; live-verified 2026-11-07 |
| Degradation reproducible from a seed | `DegradationConfig.validate` requires a seed; byte-identical output asserted per profile |
| SNR measured | achieved ratio asserted to better than 0.5 dB |
| 5 caller turns, 4 transcribed, 12 artefacts | the recorded demonstration run, `docs/COMPETITION_READINESS_REPORT.md` §4 |
| 1,999 tests / 1,958 passing / 41 skipped | `pytest` and `pytest --collect-only` |
| Evon not integrated | `evon` is refused by name; no adapter exists |
| Telephony, scoring, auth not built | `docs/DEVELOPMENT_ROADMAP.md` phases 9, 11 and 15 |

Deliberately **not** claimed: any accuracy figure or word error rate, any test
against a real voice bot, any telephone call, and any suggestion that the
simulated noise is a field recording.
