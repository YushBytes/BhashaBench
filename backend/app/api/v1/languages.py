"""The language catalogue endpoint.

Read-only: the catalogue is code, not data, so there is nothing to create or
edit. Exposed over HTTP so a dashboard or editor can populate a language
picker without hardcoding a second copy of the list.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core import accents, languages
from app.schemas.language import AccentRead, LanguageCatalogue, LanguageRead

router = APIRouter(prefix="/languages", tags=["languages"])


@router.get(
    "",
    response_model=LanguageCatalogue,
    status_code=status.HTTP_200_OK,
    summary="List supported languages",
    description=(
        "Every language a scenario may be authored in, most-spoken first, with "
        "the accent profiles a scenario in it may request. Listing a language "
        "or an accent means it can be authored and validated - not that a "
        "speech provider covers it: `/speech/providers` and "
        "`/transcription/providers` say which do, and a run records whether a "
        "requested accent was applied."
    ),
)
def list_languages() -> LanguageCatalogue:
    """Return the full catalogue."""
    entries = [
        LanguageRead.model_validate(language).model_copy(
            update={
                "accents": [
                    AccentRead.model_validate(profile)
                    for profile in accents.for_language(language.code)
                ]
            }
        )
        for language in languages.CATALOGUE
    ]
    return LanguageCatalogue(languages=entries, total=len(entries))
