"""The committed audio fixtures match their generator and their documentation.

A fixture that has silently drifted from what `generate.py` produces makes
every test using it untrustworthy - and a corrupted binary in git looks exactly
like a mysterious audio bug. These tests make either failure loud.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import tempfile
from pathlib import Path

import pytest

from app.transcription import audio as audio_tools
from app.transcription.models import AudioEncoding

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "audio"
GENERATOR = FIXTURE_DIR / "generate.py"
README = FIXTURE_DIR / "README.md"

EXPECTED_FILES = {
    "tone_8k_mono.wav",
    "tone_16k_mono.wav",
    "silence_8k_mono.wav",
    "tone_8k_stereo.wav",
    "truncated.wav",
    "not_audio.wav",
    "raw_8k_mono.pcm",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestFixturesExist:
    def test_every_expected_fixture_is_committed(self) -> None:
        present = {p.name for p in FIXTURE_DIR.iterdir() if p.is_file()}
        assert present >= EXPECTED_FILES

    def test_the_generator_is_committed_alongside_them(self) -> None:
        """A binary fixture nobody can regenerate is a binary fixture nobody
        can audit."""
        assert GENERATOR.is_file()

    def test_they_are_documented(self) -> None:
        assert README.is_file()
        text = README.read_text(encoding="utf-8")
        for name in EXPECTED_FILES:
            assert name in text, name


class TestFixturesMatchTheirGenerator:
    def test_regenerating_reproduces_every_byte(self, tmp_path: Path) -> None:
        """Deterministic by design: no RNG, no timestamps. A changed byte means
        a changed generator, which should be a deliberate commit."""
        before = {name: _digest(FIXTURE_DIR / name) for name in sorted(EXPECTED_FILES)}

        # Run the generator against a copy, so a drifted committed file is
        # reported rather than quietly overwritten by the test that found it.
        work = tmp_path / "audio"
        work.mkdir()
        shutil.copy2(GENERATOR, work / "generate.py")

        spec = importlib.util.spec_from_file_location(
            "fixture_generator_under_test", work / "generate.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate()

        after = {name: _digest(work / name) for name in sorted(EXPECTED_FILES)}
        drifted = [name for name in before if before[name] != after[name]]
        assert drifted == [], (
            f"these committed fixtures no longer match generate.py: {drifted}. "
            "Regenerate them with: "
            "python backend/tests/fixtures/audio/generate.py"
        )


class TestFixturesAreWhatTheyClaim:
    """The README's table is a promise; this checks it."""

    @pytest.mark.parametrize(
        ("name", "encoding", "sample_rate", "channels"),
        [
            ("tone_8k_mono.wav", AudioEncoding.WAV, 8000, 1),
            ("tone_16k_mono.wav", AudioEncoding.WAV, 16000, 1),
            ("silence_8k_mono.wav", AudioEncoding.WAV, 8000, 1),
        ],
    )
    def test_each_wav_has_the_documented_header(
        self, name: str, encoding: AudioEncoding, sample_rate: int, channels: int
    ) -> None:
        metadata = audio_tools.inspect((FIXTURE_DIR / name).read_bytes())
        assert metadata.encoding is encoding
        assert metadata.sample_rate_hz == sample_rate
        assert metadata.channels == channels
        assert metadata.bit_depth == 16

    def test_the_stereo_fixture_really_has_two_channels(self) -> None:
        metadata = audio_tools.inspect((FIXTURE_DIR / "tone_8k_stereo.wav").read_bytes())
        assert metadata.channels == 2

    def test_the_silence_fixture_is_actually_silent(self) -> None:
        """A fixture named `silence` that contains a tone would make the
        empty-transcript test meaningless."""
        payload = (FIXTURE_DIR / "silence_8k_mono.wav").read_bytes()
        # Skip the 44-byte canonical WAV header; the rest must be zero samples.
        assert set(payload[44:]) == {0}

    def test_the_not_audio_fixture_is_not_audio(self) -> None:
        payload = (FIXTURE_DIR / "not_audio.wav").read_bytes()
        assert audio_tools.detect_encoding(payload) is None
        assert payload.startswith(b"<!doctype html>")

    def test_the_truncated_fixture_is_detected_as_wav_but_rejected(self) -> None:
        payload = (FIXTURE_DIR / "truncated.wav").read_bytes()
        assert audio_tools.detect_encoding(payload) is AudioEncoding.WAV
        from app.transcription.errors import InvalidAudioError

        with pytest.raises(InvalidAudioError):
            audio_tools.inspect(payload)

    def test_the_raw_fixture_has_no_container(self) -> None:
        payload = (FIXTURE_DIR / "raw_8k_mono.pcm").read_bytes()
        assert audio_tools.detect_encoding(payload) is None
        assert len(payload) % 2 == 0


class TestFixtureHonesty:
    """The README must keep saying what these fixtures cannot do."""

    def test_the_readme_states_that_there_is_no_speech(self) -> None:
        """If real speech is ever added, this test should be updated in the
        same commit that adds it - and that is the point."""
        text = README.read_text(encoding="utf-8").lower()
        assert "none of these files contain speech" in text
        assert "synthesised" in text

    def test_the_readme_states_there_is_no_expected_transcript(self) -> None:
        text = README.read_text(encoding="utf-8").lower()
        assert "expected transcript" in text

    def test_the_readme_records_provenance_and_licence(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "Licence" in text or "License" in text
        assert "generate.py" in text

    def test_no_fixture_claims_an_expected_transcript_in_code(self) -> None:
        """Ground truth for audio nobody has listened to would be fabricated."""
        source = GENERATOR.read_text(encoding="utf-8")
        assert "expected_transcript" not in source


class TestFixtureFootprint:
    def test_the_total_size_stays_small(self) -> None:
        total = sum(p.stat().st_size for p in FIXTURE_DIR.iterdir() if p.is_file())
        assert total < 512 * 1024, f"audio fixtures total {total} bytes"

    def test_no_fixture_is_large_on_its_own(self) -> None:
        for path in FIXTURE_DIR.iterdir():
            if path.is_file():
                assert path.stat().st_size < 128 * 1024, path.name

    def test_nothing_was_written_outside_the_fixture_directory(self) -> None:
        """The generator writes relative to its own location; a stray absolute
        path would scatter files through the repository."""
        source = GENERATOR.read_text(encoding="utf-8")
        assert "HERE = Path(__file__).resolve().parent" in source
        assert tempfile.gettempdir() not in source
