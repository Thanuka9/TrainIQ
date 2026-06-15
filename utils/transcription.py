"""Video/audio transcription via local Whisper (optional)."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WHISPER_BIN = os.getenv("WHISPER_BIN", "whisper")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_ENABLED = os.getenv("WHISPER_ENABLED", "false").lower() in ("1", "true", "yes")


@dataclass
class TranscriptResult:
    text: str
    language: str | None
    segments: list[dict]
    source: str  # whisper | stub


def whisper_available() -> bool:
    if not WHISPER_ENABLED:
        return False
    try:
        subprocess.run(
            [WHISPER_BIN, "--help"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def transcribe_media_file(media_path: str, *, language: str | None = None) -> TranscriptResult:
    """
    Transcribe audio/video using OpenAI Whisper CLI if installed.
    Set WHISPER_ENABLED=true and install whisper: pip install openai-whisper
    """
    if not whisper_available():
        return TranscriptResult(
            text="",
            language=None,
            segments=[],
            source="stub",
        )

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            WHISPER_BIN,
            media_path,
            "--model", WHISPER_MODEL,
            "--output_format", "json",
            "--output_dir", tmp,
        ]
        if language:
            cmd.extend(["--language", language])
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=True)
        except subprocess.CalledProcessError as exc:
            logger.error("Whisper failed: %s", exc.stderr or exc)
            return TranscriptResult(text="", language=None, segments=[], source="stub")

        import json
        base = os.path.splitext(os.path.basename(media_path))[0]
        json_path = os.path.join(tmp, f"{base}.json")
        if not os.path.isfile(json_path):
            return TranscriptResult(text="", language=None, segments=[], source="stub")
        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return TranscriptResult(
            text=(data.get("text") or "").strip(),
            language=data.get("language"),
            segments=data.get("segments") or [],
            source="whisper",
        )


def attach_transcript_to_course(course_id: int, transcript: TranscriptResult) -> bool:
    """Persist transcript text on a StudyMaterial (Mongo or description field)."""
    from extensions import db
    from models import StudyMaterial

    material = StudyMaterial.query.get(course_id)
    if not material:
        return False
    suffix = f"\n\n--- Auto-transcript ({transcript.source}) ---\n{transcript.text[:8000]}"
    material.description = (material.description or "") + suffix
    db.session.commit()
    return True
