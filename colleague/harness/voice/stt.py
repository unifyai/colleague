"""Transcription for arms that expose only audio — a declared model.

The rule (see `README.md`): take the assistant's utterance text from the arm
wherever the arm speaks from text. unify-cm hands over the exact string it
fed its TTS, so it is never transcribed. An arm that only produces audio is
transcribed here, by a declared model (Deepgram `nova-3`), and the transcript
is committed with the run so a reader can check what the scorer read.

Declared because a transcription model is a second model in the loop, exactly
as the persona model is, and its identity belongs in the record.
"""

from __future__ import annotations

import io
import json
import os
import urllib.request
import wave

from colleague.harness.voice.tts import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

STT_MODEL = os.environ.get("COLLEAGUE_STT_MODEL", "nova-3")
DEEPGRAM_URL = f"https://api.deepgram.com/v1/listen?model={STT_MODEL}&smart_format=true&punctuate=true"


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe(pcm: bytes) -> str:
    """Transcribe s16le@48k mono PCM, or return '' if it cannot.

    Never raises: a transcription failure is an environment fault, and the
    caller keeps the audio and records the failure rather than crashing a run.
    """
    key = (os.environ.get("DEEPGRAM_API_KEY") or "").strip()
    if not key or not pcm:
        return ""
    try:
        req = urllib.request.Request(
            DEEPGRAM_URL,
            data=_pcm_to_wav(pcm),
            headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
        alt = body["results"]["channels"][0]["alternatives"][0]
        return str(alt.get("transcript") or "").strip()
    except Exception:  # noqa: BLE001 - transcription is best-effort evidence
        return ""
