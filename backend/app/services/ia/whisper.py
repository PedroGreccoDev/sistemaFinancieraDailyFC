from __future__ import annotations

import io

from openai import AsyncOpenAI

from app.core.config import get_settings

_EXTENSION_MAP: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/ogg; codecs=opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/webm": "webm",
    "audio/wav": "wav",
}


async def transcribir_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """Transcribe un audio de WhatsApp a texto usando Whisper-1.

    Args:
        audio_bytes: Bytes crudos del archivo de audio.
        mime_type: MIME type reportado por Evolution API.

    Returns:
        Texto transcripto en español.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    base_mime = mime_type.split(";")[0].strip()
    ext = _EXTENSION_MAP.get(base_mime, "ogg")

    buffer = io.BytesIO(audio_bytes)
    buffer.name = f"audio.{ext}"

    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=buffer,
        language="es",
    )
    return transcript.text.strip()
