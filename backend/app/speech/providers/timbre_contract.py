"""The Gnani Timbre wire contract, as published by the vendor.

Transcribed from Gnani's official developer documentation at
<https://docs.gnani.ai> - pages `api/TTS/tts-inference` (the REST reference and
its OpenAPI schema), `api/TTS/available-voices` (the voice catalogue) and
`api/introduction/introduction`. Nothing here is inferred or taken from a
third-party source.

Separate from the adapter for the same reasons as `prisma_contract`: the set of
vendor facts is auditable against the documentation in one place, and the tests
can assert against something that is not the adapter's own behaviour.

`DOCUMENTATION_GAPS` is part of the contract. Where the vendor is silent or
self-contradictory, that is recorded rather than smoothed over with a plausible
default - and in one case (the v2.5 voice roster) it changes what the adapter
is willing to validate.
"""

from __future__ import annotations

from dataclasses import dataclass

DOCUMENTATION_URL = "https://docs.gnani.ai/api/TTS/tts-inference"
"""Where every constant below comes from."""

# -- Transport --------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.vachana.ai"
"""Shared with Prisma: one Gnani platform host, one `GNANI_API_BASE_URL`."""

INFERENCE_PATH = "/api/v1/tts/inference"
"""`POST`, `application/json` in, **binary audio** out."""

API_KEY_HEADER = "X-API-Key-ID"
"""The bare key, not `Bearer`. Same header as the STT endpoints."""

# -- Request field names ----------------------------------------------------

FIELD_TEXT = "text"
FIELD_MODEL = "model"
FIELD_VOICE = "voice"
FIELD_LANGUAGE = "language"
FIELD_SPEED = "speed"
FIELD_AUDIO_CONFIG = "audio_config"

CONFIG_SAMPLE_RATE = "sample_rate"
CONFIG_NUM_CHANNELS = "num_channels"
CONFIG_SAMPLE_WIDTH = "sample_width"
CONFIG_ENCODING = "encoding"
CONFIG_CONTAINER = "container"
CONFIG_BITRATE = "bitrate"

REQUIRED_FIELDS: frozenset[str] = frozenset({FIELD_TEXT, FIELD_MODEL, FIELD_AUDIO_CONFIG})
"""Documented as required. `voice`, `language` and `speed` are optional."""

# -- Models -----------------------------------------------------------------

MODEL_V3 = "timbre-v3.0"
MODEL_V25 = "timbre-v2.5"
DEFAULT_MODEL = MODEL_V3
"""v3.0 is the model this project wants: 13 voices that each speak all ten
languages, mid-sentence code-switching, and audio tags. v2.5's voices are
language-specific, which would force a voice choice per scenario language."""

SUPPORTED_MODELS: frozenset[str] = frozenset({MODEL_V3, MODEL_V25})

# -- Voices -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Voice:
    """One Timbre voice, as the catalogue describes it."""

    name: str
    """Exact value for the `voice` field, with the documented capitalisation."""
    gender: str
    """`female` or `male`, as catalogued."""
    character: str
    """The vendor's own one-line description of the voice's intended use.

    Carried so `GET /api/v1/speech/providers` can help a scenario author pick a
    voice that suits the persona, rather than making them guess from a name.
    """


V3_VOICES: tuple[Voice, ...] = (
    Voice("Shivani", "female", "Warm, patient, empathy-first voice for inbound customer support"),
    Voice("Lakshmi", "female", "Expressive, warm voice for storytelling and e-learning narration"),
    Voice("Kalpana", "female", "Empathetic, composed voice for customer care and insurance"),
    Voice("Chetana", "female", "Gentle, empathetic voice for healthcare and telecom service"),
    Voice("Vasudha", "female", "Expressive, composed voice for narration and e-learning"),
    Voice("Riyaa", "female", "Confident, lively voice for outbound sales and insurance"),
    Voice("Tarika", "female", "Warm, reassuring voice for banking and insurance customer care"),
    Voice("Avinash", "male", "Professional, firm voice with deliberate pacing for collections"),
    Voice(
        "Shubham", "male", "Energetic, confident voice for outbound sales and lead qualification"
    ),
    Voice("Prakash", "male", "Steady, deliberate voice for payment recovery and BFSI"),
    Voice("Devansh", "male", "Energetic, young conversational voice for sales and fintech"),
    Voice("Yashraj", "male", "Warm narrative voice for e-learning and IVR narration"),
    Voice("Harshad", "male", "Professional, firm voice for collections and payment recovery"),
)
"""The 13 documented `timbre-v3.0` voices.

Every one speaks all ten supported languages, which is why this project
defaults to v3.0: a scenario's language can change without changing the voice.
"""

V3_VOICE_NAMES: frozenset[str] = frozenset(voice.name for voice in V3_VOICES)

DEFAULT_VOICE = "Kalpana"
"""Default when a caller names none.

Chosen for the subject matter rather than arbitrarily: BhashaBench's reference
scenarios are insurance, banking and delivery support calls, and this voice is
catalogued for "customer care and insurance". A caller can always override it,
and the provider has its own default if `voice` is omitted entirely - but
sending an explicit value keeps a run reproducible, which an undeclared
provider default would not.
"""

V25_VOICE_EXAMPLES: tuple[str, ...] = (
    "Nalini",
    "Bhavna",
    "Yashvi",
    "Kaveri",
    "Trupti",
    "Devika",
    "Asmita",
    "Trisha",
    "Brinda",
)
"""**Examples only - not the full roster.**

The vendor documents 42 v2.5 voices on a separate catalogue page, and only
these nine are quoted in the material consulted. Because the list is
incomplete, the adapter does **not** validate a v2.5 voice against it:
rejecting a name that is real but unquoted would be worse than forwarding it
and letting the provider decide. See `DOCUMENTATION_GAPS`.
"""

# -- Languages --------------------------------------------------------------

PROVIDER_LANGUAGE_CODES: tuple[str, ...] = (
    "hi-IN",
    "en-IN",
    "ta-IN",
    "te-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "pa-IN",
    "bn-IN",
    "gu-IN",
)
"""The ten languages Gnani documents for Timbre.

Identical to Prisma's ten, which is convenient but not something to rely on -
the mapping below is written out explicitly for the same reason it is in
`prisma_contract`.
"""

LANGUAGE_MAP: dict[str, str] = {code: code for code in PROVIDER_LANGUAGE_CODES}
"""BhashaBench tag -> Timbre `language`. Verified, not assumed."""

UNSUPPORTED_BHASHABENCH_LANGUAGES: tuple[str, ...] = ("ur-IN", "or-IN", "as-IN")
"""Catalogue languages Timbre does not document.

Urdu, Odia and Assamese - the same three Prisma lacks. A scenario may be
authored in them and no caller audio can be synthesised for it.
"""

AUTO_LANGUAGE_CODE = "auto"
"""Documented, and recommended by the vendor for mixed-script input.

Exposed by BhashaBench on the synthesis side, unlike on the recognition side.
The asymmetry is deliberate: when *recognising*, letting the provider guess
destroys the benchmark's ability to check which language the bot replied in;
when *speaking*, the caller's text is already known and `auto` is simply the
vendor's advice for a line that mixes scripts.
"""

HINGLISH_LANGUAGE_CODE = "hi-en"
"""Documented code for Hindi-English code-mixed speech.

Not a BCP 47 tag and so not in `app/core/languages.py`, but exposed on this
endpoint as an explicit option because Phase 3 made code-mixing a first-class
scenario axis and a Hinglish caller line needs a Hinglish voice.

There is **no documented Tamil-English (or any other) code-mixed code.**
`hi-en` is the only one, so a Tanglish line has to use `auto` or `ta-IN`.
"""

SUPPORTED_LANGUAGE_VALUES: frozenset[str] = frozenset(
    {*PROVIDER_LANGUAGE_CODES, AUTO_LANGUAGE_CODE, HINGLISH_LANGUAGE_CODE}
)
"""Every value the `language` field accepts."""

# -- Speed ------------------------------------------------------------------

SPEED_MIN = 0.85
SPEED_MAX = 1.15
"""Documented numeric range, inclusive."""

SPEED_ALIASES: dict[str, str] = {"slow": "slow", "medium": "medium", "fast": "fast"}
"""Documented string shortcuts, accepted in place of a number."""

# -- Audio configuration ----------------------------------------------------

SAMPLE_RATES: frozenset[int] = frozenset({8000, 16000, 22050, 24000, 44100, 48000})
DEFAULT_SAMPLE_RATE = 48000
"""Documented default."""

TELEPHONY_SAMPLE_RATE = 8000
"""Not a vendor constant - the rate an Indian phone call actually runs at, and
the one Prisma's streaming path is fed. Recorded here because it is the rate
this project will usually want, and `48000` is the vendor's default."""

DEFAULT_NUM_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2

ENCODINGS: frozenset[str] = frozenset(
    {"linear_pcm", "pcm_s16le", "pcm_mulaw", "pcm_alaw", "oggopus"}
)
DEFAULT_ENCODING = "linear_pcm"

CONTAINERS: frozenset[str] = frozenset({"wav", "raw", "mp3", "ogg", "mulaw", "alaw"})
DEFAULT_CONTAINER = "wav"

BITRATES: frozenset[str] = frozenset({"32k", "64k", "96k", "128k", "192k"})
DEFAULT_BITRATE = "128k"
"""MP3 only, per the documentation."""

MULAW_ALAW_SAMPLE_RATE = 8000
"""The `mulaw` and `alaw` containers are 8 kHz telephony codecs.

The adapter rejects any other rate for them rather than sending a combination
the vendor does not describe.
"""

CONTENT_TYPES: dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "raw": "application/octet-stream",
    "mulaw": "audio/basic",
    "alaw": "audio/basic",
}
"""Response `Content-Type` per container.

The documentation names `audio/wav`, `audio/mpeg`, `audio/ogg` and
`audio/basic`. It does not state one for `raw`, so that entry is this
project's own choice for a headerless byte stream and is marked as such in
`DOCUMENTATION_GAPS`.
"""

# -- Audio tags (v3.0 only) -------------------------------------------------

AUDIO_TAGS: tuple[str, ...] = (
    "<whispers>",
    "<laugh>",
    "<pauses>",
    "<coughs>",
    "<excited>",
    "<giggle>",
    "<shouting>",
    "<sigh>",
    "<sniffles>",
    "<yawns>",
    "<clears throat>",
)
"""Inline expression tags, documented for `timbre-v3.0` only.

Eleven are enumerated in the REST reference. The product page says "twelve
tags" without listing them, so one is unaccounted for - recorded in
`DOCUMENTATION_GAPS` rather than guessed at. Only these eleven are accepted.
"""

AUDIO_TAG_NAMES: frozenset[str] = frozenset(AUDIO_TAGS)

# -- Documented error statuses ----------------------------------------------

STATUS_BAD_REQUEST = 400
STATUS_UNAUTHORIZED = 401
STATUS_PAYMENT_REQUIRED = 402
STATUS_FORBIDDEN = 403
STATUS_RATE_LIMITED = 429
STATUS_SERVER_ERROR = 500
STATUS_UNAVAILABLE = 503

# Two documented error body shapes, which is why the adapter tries both before
# falling back to the raw text.
#   400 / 500: {"success": false, "message": "...", "status_code": NNN}
#   401 / 403 / 429: {"detail": {"error_code": "...", "message": "...", ...}}
ERROR_FIELD_MESSAGE = "message"
ERROR_FIELD_DETAIL = "detail"
ERROR_FIELD_CODE = "error_code"
ERROR_FIELD_SUCCESS = "success"

# -- Honest record of what the documentation does not settle ----------------

DOCUMENTATION_GAPS: tuple[str, ...] = (
    "The full timbre-v2.5 voice roster was not available in the material "
    "consulted - 42 voices are said to exist and nine are quoted as examples. "
    "A v2.5 voice is therefore forwarded without client-side validation; only "
    "the 13 documented v3.0 voices are validated.",
    "Voice-name case sensitivity is not stated. The documented capitalisation "
    "is sent verbatim, and a caller's differently-cased name is corrected to "
    "the documented spelling rather than forwarded as typed.",
    "The product page says timbre-v3.0 has twelve audio tags; the REST "
    "reference enumerates eleven. Only the eleven enumerated tags are "
    "accepted, so one documented capability may be missing.",
    "No maximum text length is published for the TTS endpoint. "
    "SPEECH_MAX_TEXT_CHARS is BhashaBench's own bound, not the vendor's.",
    "No rate limit or concurrency limit is published, despite 429 being a "
    "documented status. The project owner reports a one-active-request "
    "limitation; that could not be confirmed from the vendor's pages, so the "
    "adapter serialises its own calls conservatively.",
    "No Content-Type is documented for the `raw` container; "
    "application/octet-stream is BhashaBench's choice for a headerless stream.",
    "No Retry-After header is documented for 429. One is honoured if present "
    "and otherwise the client's own backoff applies.",
    "The response carries no documented request identifier, so a Timbre "
    "result has no provider request id to quote in a support ticket - unlike "
    "a Prisma transcription, which does.",
    "Whether `speed` string shortcuts and numeric values behave identically "
    "is not stated; both are forwarded as documented without interpretation.",
)


def voice_for(name: str) -> Voice | None:
    """Return the documented v3.0 voice matching `name`, case-insensitively."""
    folded = name.strip().casefold()
    for voice in V3_VOICES:
        if voice.name.casefold() == folded:
            return voice
    return None


__all__ = [
    "API_KEY_HEADER",
    "AUDIO_TAGS",
    "AUDIO_TAG_NAMES",
    "AUTO_LANGUAGE_CODE",
    "BITRATES",
    "CONFIG_BITRATE",
    "CONFIG_CONTAINER",
    "CONFIG_ENCODING",
    "CONFIG_NUM_CHANNELS",
    "CONFIG_SAMPLE_RATE",
    "CONFIG_SAMPLE_WIDTH",
    "CONTAINERS",
    "CONTENT_TYPES",
    "DEFAULT_BASE_URL",
    "DEFAULT_BITRATE",
    "DEFAULT_CONTAINER",
    "DEFAULT_ENCODING",
    "DEFAULT_MODEL",
    "DEFAULT_NUM_CHANNELS",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_SAMPLE_WIDTH",
    "DEFAULT_VOICE",
    "DOCUMENTATION_GAPS",
    "DOCUMENTATION_URL",
    "ENCODINGS",
    "ERROR_FIELD_CODE",
    "ERROR_FIELD_DETAIL",
    "ERROR_FIELD_MESSAGE",
    "ERROR_FIELD_SUCCESS",
    "FIELD_AUDIO_CONFIG",
    "FIELD_LANGUAGE",
    "FIELD_MODEL",
    "FIELD_SPEED",
    "FIELD_TEXT",
    "FIELD_VOICE",
    "HINGLISH_LANGUAGE_CODE",
    "INFERENCE_PATH",
    "LANGUAGE_MAP",
    "MODEL_V3",
    "MODEL_V25",
    "MULAW_ALAW_SAMPLE_RATE",
    "PROVIDER_LANGUAGE_CODES",
    "REQUIRED_FIELDS",
    "SAMPLE_RATES",
    "SPEED_ALIASES",
    "SPEED_MAX",
    "SPEED_MIN",
    "STATUS_BAD_REQUEST",
    "STATUS_FORBIDDEN",
    "STATUS_PAYMENT_REQUIRED",
    "STATUS_RATE_LIMITED",
    "STATUS_SERVER_ERROR",
    "STATUS_UNAUTHORIZED",
    "STATUS_UNAVAILABLE",
    "SUPPORTED_LANGUAGE_VALUES",
    "SUPPORTED_MODELS",
    "TELEPHONY_SAMPLE_RATE",
    "UNSUPPORTED_BHASHABENCH_LANGUAGES",
    "V3_VOICES",
    "V3_VOICE_NAMES",
    "V25_VOICE_EXAMPLES",
    "Voice",
    "voice_for",
]
