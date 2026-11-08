"""Pipeline domain errors.

`DomainError` subclasses, like every other failure in this project, so the
handlers in `app/main.py` stay the single place an error becomes an HTTP
status. Nothing here raises `HTTPException`.
"""

from __future__ import annotations

from app.services.errors import DomainError


class PipelineError(DomainError):
    """Base class for every pipeline failure.

    Attributes:
        run_id: The run this concerns, when there is one.
        stage: Which step of the turn lifecycle failed. A run that broke at
            synthesis and one that broke at transcription need different
            investigation, and the stage is what says which without parsing
            the message.
    """

    def __init__(
        self,
        message: str,
        *,
        run_id: str | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.stage = stage


class PipelineConfigurationError(PipelineError):
    """The run cannot be built from the settings and arguments given.

    An unimplemented execution mode, a degradation profile that does not
    exist, a mode whose required adapter is absent.
    """


class RunNotActiveError(PipelineError):
    """The run has already reached a terminal status."""


class RunCancelledError(PipelineError):
    """The run was cancelled while a turn was in flight.

    Distinct from `RunNotActiveError`: that one means "you asked too late",
    this one means "it stopped underneath you". The first is the client's
    mistake and the second is not.
    """


class RunCapacityExhaustedError(PipelineError):
    """Every concurrent-run slot is in use, so this run was not started.

    Not a failure of the run: it keeps whatever state it had, nothing is
    persisted and nothing is lost, so the client can retry when a slot frees
    up. The API answers 503 for exactly that reason - the condition is
    temporary and about the server's capacity, not about the request.

    Attributes:
        limit: The configured maximum, so a client is told what it hit.
        in_use: How many were running when the refusal happened.
    """

    def __init__(
        self,
        message: str,
        *,
        limit: int | None = None,
        in_use: int | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message, run_id=run_id, stage="admission")
        self.limit = limit
        self.in_use = in_use


class ArtefactAccessDisabledError(PipelineError):
    """Stored conversation audio may not be streamed in this environment.

    Not a missing artefact and not a bad request: the recording exists and the
    reference resolves, but this process is running somewhere the route is
    switched off. The application has no authentication, so on a reachable
    host an open artefact route would let anyone hear a recorded conversation.
    Development serves audio because the operator is the only listener;
    staging and production refuse until `PIPELINE_SERVE_ARTEFACTS` says
    otherwise.
    """


class AudioValidationError(PipelineError):
    """Audio entering or leaving a stage failed inspection.

    Raised rather than swallowed, because §6 is explicit that invalid audio
    must never be stored as a successful turn. The run records
    `AUDIO_VALIDATION_FAILED`, which is deliberately not a statement about the
    bot.
    """


class DegradationError(PipelineError):
    """The degradation engine could not process the audio.

    Either the input is not 16-bit PCM WAV, or a transformation parameter is
    outside its documented range.
    """


class BotAdapterError(PipelineError):
    """The bot adapter failed to return usable audio.

    Attributes:
        adapter: Registry name of the adapter, so a report can say which
            integration was unavailable rather than only that one was.
        retryable: Whether trying again could plausibly work. A timeout might;
            a malformed reply will not.
    """

    def __init__(
        self,
        message: str,
        *,
        adapter: str | None = None,
        retryable: bool = False,
        run_id: str | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message, run_id=run_id, stage=stage)
        self.adapter = adapter
        self.retryable = retryable


class BotUnavailableError(BotAdapterError):
    """The bot could not be reached at all."""


class BotTimeoutError(BotAdapterError):
    """The bot did not reply within the configured timeout."""


class BotAudioPendingError(BotAdapterError):
    """The bot's audio has not been supplied yet.

    Not a failure. The manual adapter raises this to say "the run is waiting
    for you", which the API turns into a 409 rather than a 502 - a run awaiting
    input is healthy, and recording it as a bot outage would be false.
    """


__all__ = [
    "ArtefactAccessDisabledError",
    "AudioValidationError",
    "BotAdapterError",
    "BotAudioPendingError",
    "BotTimeoutError",
    "BotUnavailableError",
    "DegradationError",
    "PipelineConfigurationError",
    "PipelineError",
    "RunCancelledError",
    "RunCapacityExhaustedError",
    "RunNotActiveError",
]
