"""Word-level transcription with faster-whisper (free, runs on the user's own CPU).

Why faster-whisper: it is Whisper converted to CTranslate2, so the "small" model transcribes a
4.5-minute clip in under a minute on 4 CPU cores with int8, and gives a start and end time for
every word. The model (about 480 MB) downloads once from Hugging Face on first use.

Whisper is trained to write clean text and normally drops "um" and "uh", or hides them inside
the next word's timing. Two things make it write them out, because the editor needs to see them
to cut them:
- an initial prompt full of fillers, and
- transcribing phrase by phrase (chunks of up to 12 s split at pauses) instead of 30 s windows,
  so the prompt steers every phrase. On a real 4.5-minute clip this found 25 fillers instead of 3,
  in the same time.

Audio is decoded by our own FFmpeg into raw floats, so we don't depend on PyAV's file reader.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from app.engine.audio import Interval

log = logging.getLogger("framework.transcribe")

SAMPLE_RATE = 16000
FILLER_PROMPT = "Umm, so, em, I I mean, uh, like, you know, hmm. Erm, okay. Ah, so so we, we went."


class TranscribeError(RuntimeError):
    pass


class Word(BaseModel):
    i: int
    start: float
    end: float
    text: str  # as spoken, with punctuation, no surrounding spaces
    prob: float = 1.0


class Transcript(BaseModel):
    model: str
    language: str
    method: str = "phrases"
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def decode_audio(src: Path, ffmpeg: str = "ffmpeg") -> np.ndarray:
    cmd = [ffmpeg, "-v", "error", "-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
           "-f", "f32le", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise TranscribeError(f"'{ffmpeg}' not found. Install FFmpeg and add it to PATH.") from exc
    if result.returncode != 0:
        raise TranscribeError("Could not read the audio: " + result.stderr.decode(errors="replace").strip()[-300:])
    return np.frombuffer(result.stdout, dtype=np.float32)


_models: dict[str, object] = {}
_lock = threading.Lock()


def _model(size: str):
    with _lock:
        if size not in _models:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscribeError("Transcription needs faster-whisper: pip install -r requirements.txt") from exc
            log.info("Loading Whisper model '%s' (downloads once, about 480 MB for 'small')", size)
            _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
        return _models[size]


def phrase_chunks(speech: list[Interval] | None, duration: float, max_len: float = 12.0,
                  pad: float = 0.2) -> list[tuple[float, float]]:
    """Group spoken parts into chunks of at most `max_len` seconds, split at pauses."""
    if not speech:
        return [(t, min(duration, t + 30.0)) for t in np.arange(0.0, duration, 30.0)]
    chunks: list[list[float]] = []
    for iv in sorted(speech, key=lambda i: i.start):
        if chunks and iv.end - chunks[-1][0] <= max_len:
            chunks[-1][1] = iv.end
        else:
            chunks.append([iv.start, iv.end])
    return [(max(0.0, a - pad), min(duration, b + pad)) for a, b in chunks]


def transcribe(src: Path, ffmpeg: str = "ffmpeg", model_size: str = "small",
               language: str | None = "en", speech: list[Interval] | None = None) -> Transcript:
    """Transcribe with word timings. Pass the spoken parts from silence analysis to go phrase by phrase."""
    audio = decode_audio(src, ffmpeg)
    if audio.size == 0:
        return Transcript(model=model_size, language=language or "", words=[])
    duration = audio.size / SAMPLE_RATE
    words: list[Word] = []
    detected = language or ""
    try:
        model = _model(model_size)
        for a, b in phrase_chunks(speech, duration):
            piece = audio[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)]
            if piece.size < SAMPLE_RATE // 10:
                continue
            segments, info = model.transcribe(
                piece, language=language, word_timestamps=True, initial_prompt=FILLER_PROMPT,
                condition_on_previous_text=False, vad_filter=False)
            detected = detected or info.language
            for seg in segments:
                for w in seg.words or []:
                    text = w.word.strip()
                    start, end = round(a + w.start, 3), round(a + w.end, 3)
                    if text and (not words or start >= words[-1].start):
                        words.append(Word(i=len(words), start=start, end=end, text=text,
                                          prob=round(w.probability, 3)))
    except TranscribeError:
        raise
    except Exception as exc:  # model download or decoding problems surface here
        raise TranscribeError(f"Transcription failed: {exc}") from exc
    return Transcript(model=model_size, language=detected, words=words)
