"""Response models for the language catalogue."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccentRead(BaseModel):
    """An accent profile: a label for a speaker population, not a sound."""

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(description="Value for a scenario's `persona.accent`.")
    name: str
    description: str


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
    accents: list[AccentRead] = Field(
        default_factory=list,
        description=(
            "Accent profiles a scenario in this language may request. Listing one "
            "does not mean any speech provider can render it; a run reports that."
        ),
    )


class LanguageCatalogue(BaseModel):
    """Every language a scenario may be authored in."""

    languages: list[LanguageRead] = Field(description="Supported languages, most-spoken first.")
    total: int = Field(ge=0, description="How many are supported.")
