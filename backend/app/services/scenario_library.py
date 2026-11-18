"""The reference scenarios that ship with the repository, as a library.

`scenarios/*.yaml` is the one-per-language reference survey and
`scenarios/demo/*.yaml` the demonstration. Both are copied into the
production image at `/scenarios`, which `REPO_ROOT` resolves to. A
signed-in user can start from one of them in the UI instead of copying YAML
out of the repository.

Read-only and global: these are files in the image, not tenant data, and
reading them adds nothing to any workspace. Adding one to a suite still
goes through the ordinary validated `POST /suites/{id}/scenarios`, in the
caller's own workspace. No caller-supplied path reaches the filesystem; the
set of files is fixed by the globs below. Every entry is parsed with the
same validating loader as an upload, so a library entry that stopped
validating would fail here rather than at "Add to suite".
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import REPO_ROOT
from app.services.scenario_loader import spec_from_yaml

SCENARIO_DIR = REPO_ROOT / "scenarios"
GLOBS = ("*.yaml", "demo/*.yaml")
"""`bundles/` is excluded: a bundle is many scenarios in one document."""


@dataclass(frozen=True, slots=True)
class LibraryScenario:
    key: str
    """Path under `scenarios/` without `.yaml`, e.g. `demo/tamil_crop_insurance`."""
    name: str
    language: str
    description: str | None
    objective: str
    yaml: str


def _load(directory: Path) -> tuple[LibraryScenario, ...]:
    entries: list[LibraryScenario] = []
    for pattern in GLOBS:
        for path in sorted(directory.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            spec = spec_from_yaml(text)
            entries.append(
                LibraryScenario(
                    key=path.relative_to(directory).with_suffix("").as_posix(),
                    name=spec.name,
                    language=spec.language,
                    description=spec.description,
                    objective=spec.goal.objective,
                    yaml=text,
                )
            )
    return tuple(entries)


@lru_cache(maxsize=1)
def reference_scenarios() -> tuple[LibraryScenario, ...]:
    """Every shipped scenario. Read once: the files are part of the image."""
    if not SCENARIO_DIR.is_dir():
        return ()
    return _load(SCENARIO_DIR)


__all__ = ["GLOBS", "SCENARIO_DIR", "LibraryScenario", "reference_scenarios"]
