"""Response models for the language catalogue."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LanguageRead(BaseModel):
    """One supported language."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "code": "hi-IN",
                "name": "Hindi",
                "endonym": "हिन्दी",
                "script": "Deva",
                "locale": "hi_IN",
            }
        },
    )

    code: str = Field(description="Canonical BCP 47 tag, as stored on a scenario.")
    name: str = Field(description="English display name.")
    endonym: str = Field(description="The language's name in its own script.")
    script: str = Field(description="ISO 15924 script code.")
    locale: str = Field(description="Underscore locale form, for ICU-style consumers.")


class LanguageCatalogue(BaseModel):
    """Every language a scenario may be authored in."""

    languages: list[LanguageRead] = Field(description="Supported languages, most-spoken first.")
    total: int = Field(ge=0, description="How many are supported.")
