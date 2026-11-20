"""Write the caller-phrase review sheet a fluent speaker fills in.

    python scripts/phrase_review_sheet.py            # writes docs/phrase-review/*.csv
    python scripts/phrase_review_sheet.py --check    # exits 1 if the sheets are stale

One CSV per unreviewed language, generated from the phrase tables the caller
actually speaks (`backend/app/caller/providers/deterministic.py`), so a
reviewer never reviews a copy that has drifted. The reviewer columns start
empty and the status column starts `pending`: nothing here records a review
until a person fills it in, and only moving the language to the reviewed set
in code (see `docs/PHRASE_REVIEW.md`) signs it off.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.caller.providers import deterministic  # noqa: E402

OUT = ROOT / "docs" / "phrase-review"
USE = {
    "opening": "first turn; {identity} and {objective} come from the scenario",
    "ask": "the caller asks for information",
    "provide_fact": "the bot asked for something the caller knows; {fact} is a scenario fact",
    "clarify": "the bot's reply could not be used",
    "repeat_request": "the bot's reply was empty or unclear",
    "correct": "the bot stated a known fact wrongly",
    "decline_unknown": "the bot asked for something the caller does not know",
    "confirm": "reading back what the bot said",
    "close_success": "the goal was reached",
    "close_failure": "the caller gives up",
}
COLUMNS = [
    "language", "slot", "phrase", "english_reference", "used_when",
    "status", "decision", "suggested_phrase", "reviewer", "reviewed_on", "notes",
]  # fmt: skip


def sheet(language: str) -> str:
    table = deterministic._TABLES[language]
    english = deterministic._TABLES["en-IN"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for f in fields(table):
        writer.writerow([
            language, f.name, getattr(table, f.name), getattr(english, f.name), USE[f.name],
            "pending", "", "", "", "", "",
        ])  # fmt: skip
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="fail if a sheet is stale")
    args = parser.parse_args()
    stale = []
    for language in sorted(deterministic._UNREVIEWED_LANGUAGES):
        path = OUT / f"{language}.csv"
        text = sheet(language)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
            continue
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print(
            f"stale review sheets: {stale}; rerun scripts/phrase_review_sheet.py", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
