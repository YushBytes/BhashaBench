"""The language catalogue endpoint.

Read-only: the catalogue is code, not data, so there is nothing to create or
edit. Exposed over HTTP so a dashboard or editor can populate a language
picker without hardcoding a second copy of the list.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core import languages
from app.schemas.language import LanguageCatalogue, LanguageRead

router = APIRouter(prefix="/languages", tags=["languages"])


@router.get(
    "",
    response_model=LanguageCatalogue,
    status_code=status.HTTP_200_OK,
    summary="List supported languages",
    description=(
        "Every language a scenario may be authored in, most-spoken first. "
        "Listing a language means it can be authored and validated - not that "
        "speech recognition or synthesis exists for it; no provider is "
        "integrated yet."
    ),
)
def list_languages() -> LanguageCatalogue:
    """Return the full catalogue."""
    entries = [LanguageRead.model_validate(language) for language in languages.CATALOGUE]
    return LanguageCatalogue(languages=entries, total=len(entries))
