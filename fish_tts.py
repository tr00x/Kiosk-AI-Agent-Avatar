"""Custom Pipecat TTS service for a local Fish Speech v1.4 API server.

Fish Speech runs locally via:
    cd /Users/timur/fish-speech
    .venv/bin/python tools/api.py --listen 127.0.0.1:8090 --device mps --mode tts

This service sends text to /v1/tts, receives WAV audio, and streams
raw PCM int16 frames into the pipecat pipeline.
"""

import io
import struct
import wave
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

# Fish Speech v1.4 decoder outputs 44100 Hz mono audio
FISH_SAMPLE_RATE = 44100
PCM_CHUNK = 8192  # bytes per frame yield


class FishSpeechTTSService(TTSService):
    """Streams TTS audio from a local Fish Speech v1.4 server."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8090",
        reference_id: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.7,
        repetition_penalty: float = 1.2,
        chunk_length: int = 200,
        **kwargs,
    ):
        super().__init__(sample_rate=FISH_SAMPLE_RATE, **kwargs)
        self._base_url = base_url.rstrip("/")
        self._reference_id = reference_id
        self._temperature = temperature
        self._top_p = top_p
        self._repetition_penalty = repetition_penalty
        self._chunk_length = chunk_length
        self._session: Optional[aiohttp.ClientSession] = None

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._session = aiohttp.ClientSession()

    async def stop(self, frame):
        await super().stop(frame)
        if self._session:
            await self._session.close()
            self._session = None

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"FishSpeechTTS: [{text}]")

        try:
            await self.start_ttfb_metrics()
            await self.start_tts_usage_metrics(text)

            yield TTSStartedFrame(context_id=context_id)

            payload = {
                "text": text,
                "format": "wav",
                "streaming": False,
                "chunk_length": self._chunk_length,
                "normalize": True,
                "latency": "balanced",
                "temperature": self._temperature,
                "top_p": self._top_p,
                "repetition_penalty": self._repetition_penalty,
            }
            if self._reference_id:
                payload["reference_id"] = self._reference_id

            url = f"{self._base_url}/v1/tts"

            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"FishSpeechTTS: {resp.status} — {body}")
                    yield ErrorFrame(error=f"Fish Speech error {resp.status}: {body}")
                    return

                wav_bytes = await resp.read()

            await self.stop_ttfb_metrics()

            # Parse WAV → raw PCM int16
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                sr = wf.getframerate()
                n_frames = wf.getnframes()
                sw = wf.getsampwidth()  # bytes per sample
                raw = wf.readframes(n_frames)

            # Convert to int16 if needed (WAV from Fish is typically int16 already)
            if sw == 2:
                pcm = raw
            elif sw == 4:
                # float32 → int16
                n_samples = len(raw) // 4
                floats = struct.unpack(f"<{n_samples}f", raw)
                pcm = struct.pack(
                    f"<{n_samples}h",
                    *(max(-32768, min(32767, int(s * 32767))) for s in floats),
                )
            else:
                pcm = raw

            # Stream PCM in chunks
            for i in range(0, len(pcm), PCM_CHUNK):
                yield TTSAudioRawFrame(
                    audio=pcm[i : i + PCM_CHUNK],
                    sample_rate=sr,
                    num_channels=1,
                    context_id=context_id,
                )

            yield TTSStoppedFrame(context_id=context_id)

        except Exception as e:
            logger.error(f"FishSpeechTTS: {e}")
            yield ErrorFrame(error=str(e))
        finally:
            await self.stop_ttfb_metrics()
