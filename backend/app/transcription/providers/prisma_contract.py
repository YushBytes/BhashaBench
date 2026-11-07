"""The Gnani Prisma wire contract, as published by the vendor.

Everything in this module is transcribed from Gnani's official developer
documentation at <https://docs.gnani.ai> (pages consulted: `api/introduction/
introduction`, `api/introduction/quick-start`, and `api/use-cases/
real-time-compliance`, which carries the worked WebSocket example). Nothing
here is inferred, guessed or copied from a third-party blog post.

It is a separate module from the adapter for two reasons. It makes the set of
vendor-specific facts auditable in one place against the documentation, and it
gives the tests something to assert against that is not the adapter's own
behaviour.

`DOCUMENTATION_GAPS` is part of the contract too. Where the vendor's own pages
disagree or go quiet, the honest record of that belongs next to the parts that
are settled - not smoothed over with a plausible default.
"""

from __future__ import annotations

from app.transcription.models import AudioEncoding, TranscriptionMode

DOCUMENTATION_URL = "https://docs.gnani.ai"
"""Where every constant below comes from."""

# -- Transport --------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.vachana.ai"
"""Documented REST base URL. Overridable via `GNANI_API_BASE_URL`."""

DEFAULT_WS_BASE_URL = "wss://api.vachana.ai"
"""Documented WebSocket base URL."""

BATCH_PATH = "/stt/v3"
"""`POST`, `multipart/form-data`. Single-shot transcription of one file."""

STREAM_PATH = "/stt/v3/stream"
"""WebSocket endpoint. Authenticated on the upgrade request's headers."""

# -- Authentication ---------------------------------------------------------

API_KEY_HEADER = "X-API-Key-ID"
"""REST spelling. The key is sent as the bare header value - not `Bearer`."""

WS_API_KEY_HEADER = "x-api-key-id"
"""Lower-case spelling used by the documented WebSocket example.

HTTP header names are case-insensitive, so this is cosmetic; it is kept
verbatim so the code matches the documentation a reviewer will compare against.
"""

# -- Multipart field names (REST) -------------------------------------------

FIELD_AUDIO = "audio_file"
FIELD_MODEL = "model"
FIELD_LANGUAGE = "language_code"
FIELD_FORMAT = "format"

# -- Models -----------------------------------------------------------------

MODEL_V3 = "prisma-v3.0"
MODEL_V25 = "prisma-v2.5"
DEFAULT_MODEL = MODEL_V3
"""v3.0 is the current model and the one documented for code-mixed Indian
call audio, which is this project's entire subject. The vendor's documented
API default is v2.5, so the adapter always sends the field explicitly rather
than relying on it."""

SUPPORTED_MODELS: frozenset[str] = frozenset({MODEL_V3, MODEL_V25})

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
"""The ten languages Gnani documents for Prisma STT.

BhashaBench's catalogue holds thirteen. Prisma's codes happen to be spelled
identically to ours, so the mapping is the identity function - but it is
written out as an explicit map anyway, because an identity mapping that is
*assumed* becomes a silent bug the first time a provider spells Punjabi
`pa-Guru-IN`.
"""

LANGUAGE_MAP: dict[str, str] = {code: code for code in PROVIDER_LANGUAGE_CODES}
"""BhashaBench tag -> Prisma `language_code`. Verified, not assumed."""

UNSUPPORTED_BHASHABENCH_LANGUAGES: tuple[str, ...] = ("ur-IN", "or-IN", "as-IN")
"""Catalogue languages Prisma does not document support for.

Urdu, Odia and Assamese. A scenario may be authored in them - Phase 3 allows
it - but no transcript can be produced, and the service refuses the request
rather than transcribing as a neighbouring language.
"""

AUTO_LANGUAGE_CODE = "auto"
"""Documented value for automatic detection.

Not offered through BhashaBench's API in this phase. The vendor's pages use
both `auto` and `indic-auto` without stating how they differ (see
`DOCUMENTATION_GAPS`), and a benchmark that silently detects the language
cannot report whether the bot answered in the language the scenario asked for.
"""

HINGLISH_LANGUAGE_CODE = "hi-en"
"""Documented Prisma code for Hindi-English code-mixed speech.

Deliberately not added to BhashaBench's catalogue: `app/core/languages.py` is
the single source of truth and `hi-en` is not a BCP 47 tag that the scenario
schema accepts. Code-mixing is already expressed in the scenario's
`code_mixing` block, and `TranscriptionMode.CODE_MIX` is the output-side
control. Recorded here so the capability is not lost.
"""

# -- Output modes -----------------------------------------------------------

MODE_MAP: dict[TranscriptionMode, str] = {
    TranscriptionMode.TRANSCRIBE: "transcribe",
}
"""BhashaBench mode -> Prisma `format` value, for modes whose literal wire
value the documentation states.

Only `transcribe` is quoted verbatim in the vendor's examples (the REST
quick-start, and the streaming header note "set `format` to `transcribe` for
ITN"). Prisma v3.0 is described as offering four output modes - Verbatim,
Transcribe, Code-mix and Transliterate - but the other three appear only as
prose names, never as literal API values. Guessing `code-mix` versus
`code_mix` versus `codemix` would be inventing the contract, which is
precisely what must not happen here, so the other three are declared
unsupported until the literals are confirmed.
"""

SUPPORTED_MODES: frozenset[TranscriptionMode] = frozenset(MODE_MAP)

# -- Audio ------------------------------------------------------------------

BATCH_ENCODINGS: frozenset[AudioEncoding] = frozenset(
    {
        AudioEncoding.WAV,
        AudioEncoding.MP3,
        AudioEncoding.OGG,
        AudioEncoding.FLAC,
        AudioEncoding.AAC,
        AudioEncoding.M4A,
    }
)
""""WAV, MP3, OGG, FLAC, AAC, M4A (STT)", quoted from the specifications page."""

STREAMING_ENCODINGS: frozenset[AudioEncoding] = frozenset({AudioEncoding.PCM_S16LE})
"""Streaming takes raw PCM only: "PCM signed 16-bit little-endian, mono"."""

STREAMING_SAMPLE_RATES: frozenset[int] = frozenset({8000, 16000, 44100, 48000})
"""Values documented for the `x-sample-rate` header."""

DEFAULT_STREAMING_SAMPLE_RATE = 16000
"""Documented default when `x-sample-rate` is omitted."""

STREAM_FRAME_BYTES = 1024
"""Documented: "Each WebSocket frame must be exactly 1024 bytes."

512 samples - 32 ms at 16 kHz, 64 ms at 8 kHz. The documentation also warns
that bursting frames faster than real time degrades voice-activity detection,
which is why the adapter paces its sends rather than flushing a buffer.
"""

STREAMING_CHANNELS = 1
"""Mono only."""

BATCH_MAX_BYTES_PER_FILE = 10 * 1024 * 1024
"""10 MB, documented for the asynchronous batch-jobs API.

Applied to the single-shot REST path as a conservative ceiling: the vendor
does not publish a size limit for `POST /stt/v3`, and the documented limit for
its sibling endpoint is a far better guess than none. The effective limit is
whichever is smaller, this or `TRANSCRIPTION_MAX_UPLOAD_BYTES`.
"""

# -- Streaming event types --------------------------------------------------

EVENT_CONNECTED = "connected"
"""Sent after the handshake. Fields: `message`, `config.sample_rate`,
`config.chunk_size`, `timestamp`."""

EVENT_PROCESSING = "processing"
"""Sent when voice-activity detection reports end-of-speech."""

EVENT_TRANSCRIPT = "transcript"
"""A completed segment. Fields: `text`, `segment_index`, `segment_id`,
`audio_duration_ms`, `latency`, `timestamp`.

There is no `is_final` field and no partial-result indicator in the documented
schema: every `transcript` event is a settled segment. The adapter therefore
emits `FinalTranscript` for each one and never emits `PartialTranscript`.
"""

EVENT_ERROR = "error"
"""Server-side error. Fields: `message`, `timestamp`."""

# -- Response field names (REST) --------------------------------------------

RESPONSE_SUCCESS = "success"
RESPONSE_REQUEST_ID = "request_id"
RESPONSE_TRANSCRIPT = "transcript"
RESPONSE_MODEL = "model"
RESPONSE_DETECTED_LANGUAGE = "detected_language_code"
RESPONSE_PROCESSING_TIME = "processing_time"
RESPONSE_END_TO_END_LATENCY = "end_to_end_latency"

# -- Documented HTTP status codes -------------------------------------------

STATUS_UNAUTHORIZED = 401
"""Missing or invalid API key."""
STATUS_PAYMENT_REQUIRED = 402
"""Insufficient credit."""
STATUS_FORBIDDEN = 403
"""The key lacks the required scope."""
STATUS_RATE_LIMITED = 429
"""Too many requests."""

# -- Honest record of what the documentation does not settle ----------------

DOCUMENTATION_GAPS: tuple[str, ...] = (
    "Maximum audio duration for POST /stt/v3 is stated inconsistently by the "
    "vendor: the specifications page says 30 seconds, the quick-start says 60. "
    "No duration limit is enforced client-side; the provider's own rejection "
    "is surfaced instead of a guessed ceiling.",
    "No request body size limit is published for POST /stt/v3. The 10 MB "
    "per-file limit documented for the batch-jobs API is applied as a "
    "conservative ceiling.",
    "Literal `format` values are published only for `transcribe`. Verbatim, "
    "code-mix and transliterate are described by name but their wire values "
    "are not quoted, so they are declared unsupported rather than guessed.",
    "`auto` and `indic-auto` both appear as language_code values without a "
    "stated difference. Neither is exposed by BhashaBench in this phase.",
    "No Retry-After header is documented for 429. The adapter honours one if "
    "present and otherwise falls back to its own exponential backoff.",
    "The streaming protocol documents no end-of-stream acknowledgement, so "
    "the adapter treats a normal socket close as completion.",
    "Confidence scores, word-level timestamps and speaker diarisation do not "
    "appear in the documented STT response schemas and are reported as "
    "unsupported rather than synthesised.",
)


__all__ = [
    "API_KEY_HEADER",
    "AUTO_LANGUAGE_CODE",
    "BATCH_ENCODINGS",
    "BATCH_MAX_BYTES_PER_FILE",
    "BATCH_PATH",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_STREAMING_SAMPLE_RATE",
    "DEFAULT_WS_BASE_URL",
    "DOCUMENTATION_GAPS",
    "DOCUMENTATION_URL",
    "EVENT_CONNECTED",
    "EVENT_ERROR",
    "EVENT_PROCESSING",
    "EVENT_TRANSCRIPT",
    "FIELD_AUDIO",
    "FIELD_FORMAT",
    "FIELD_LANGUAGE",
    "FIELD_MODEL",
    "HINGLISH_LANGUAGE_CODE",
    "LANGUAGE_MAP",
    "MODEL_V3",
    "MODEL_V25",
    "MODE_MAP",
    "PROVIDER_LANGUAGE_CODES",
    "RESPONSE_DETECTED_LANGUAGE",
    "RESPONSE_END_TO_END_LATENCY",
    "RESPONSE_MODEL",
    "RESPONSE_PROCESSING_TIME",
    "RESPONSE_REQUEST_ID",
    "RESPONSE_SUCCESS",
    "RESPONSE_TRANSCRIPT",
    "STATUS_FORBIDDEN",
    "STATUS_PAYMENT_REQUIRED",
    "STATUS_RATE_LIMITED",
    "STATUS_UNAUTHORIZED",
    "STREAMING_CHANNELS",
    "STREAMING_ENCODINGS",
    "STREAMING_SAMPLE_RATES",
    "STREAM_FRAME_BYTES",
    "STREAM_PATH",
    "SUPPORTED_MODELS",
    "SUPPORTED_MODES",
    "UNSUPPORTED_BHASHABENCH_LANGUAGES",
    "WS_API_KEY_HEADER",
]
