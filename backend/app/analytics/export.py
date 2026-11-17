"""CSV and JSON exports of runs and their evidence.

**CSV injection.** A bot's reply is untrusted text, and a spreadsheet opens a
cell beginning with `=`, `+`, `-`, `@`, a tab or a carriage return as a
formula - so a bot that says `=HYPERLINK(...)` would execute in the analyst's
spreadsheet. Every cell goes through `safe_cell`, which prefixes such a cell
with an apostrophe (the OWASP-recommended neutralisation). JSON needs no such
treatment and is exported unaltered.

Exports carry their provenance: the evaluator version, the evidence
fingerprint and the export time, so a file can be traced back to the stored
run and shown to be current or stale.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

RUN_COLUMNS = (
    "run_id",
    "created_at",
    "suite_id",
    "scenario_name",
    "language",
    "mode",
    "bot_adapter",
    "status",
    "outcome",
    "verdict",
    "wer",
    "cer",
    "bot_response_latency_p50_ms",
    "uses_language_model",
)

TURN_COLUMNS = (
    "turn_index",
    "speaker",
    "text",
    "source",
    "latency_ms",
    "transcription_error",
    "reference",
)


def safe_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def to_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return buffer.getvalue()


__all__ = ["RUN_COLUMNS", "TURN_COLUMNS", "safe_cell", "to_csv"]
