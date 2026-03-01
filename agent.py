"""Agent module: wires STT, LLM, TTS, Simli face, and SmallWebRTC transport into a pipeline."""

import os
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from fish_tts import FishSpeechTTSService
from pipecat.services.simli.video import SimliVideoService
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.base_transport import TransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame, TranscriptionFrame, TextFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame,
)

from pipecat_flows import FlowManager
from tools import broadcast_event as tool_broadcast


class TranscriptProcessor(FrameProcessor):
    """Captures user/bot text and broadcasts via WebSocket."""

    def __init__(self, role: str, **kwargs):
        super().__init__(**kwargs)
        self._role = role
        self._bot_text = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if self._role == "user" and isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                await tool_broadcast("user_transcript", {"text": text})

        if self._role == "bot":
            if isinstance(frame, LLMFullResponseStartFrame):
                self._bot_text = ""
            elif isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
                self._bot_text += frame.text
                await tool_broadcast("bot_transcript", {"text": self._bot_text})
            elif isinstance(frame, LLMFullResponseEndFrame):
                self._bot_text = ""
                await tool_broadcast("bot_stopped_speaking", {})

        await self.push_frame(frame, direction)


async def create_agent(
    webrtc_connection: SmallWebRTCConnection,
) -> tuple[PipelineTask, SmallWebRTCTransport, FlowManager]:
    """Create pipeline with Simli face + SmallWebRTC transport."""

    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    simli_api_key = os.getenv("SIMLI_API_KEY", "")
    simli_face_id = os.getenv("SIMLI_FACE_ID", "")
    fish_url = os.getenv("FISH_SPEECH_URL", "http://localhost:8090")
    fish_ref = os.getenv("FISH_SPEECH_REF", None)

    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if not simli_api_key:
        raise RuntimeError("SIMLI_API_KEY is not set")
    if not simli_face_id:
        raise RuntimeError("SIMLI_FACE_ID is not set")

    # --- Transport (SmallWebRTC — browser <-> bot via WebRTC) ---
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_out_enabled=True,
            video_out_width=512,
            video_out_height=512,
            video_out_framerate=30,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                confidence=0.8,
                start_secs=0.8,
                stop_secs=1.5,
                min_volume=0.7,
            )),
        ),
    )

    # --- STT (OpenAI Realtime — WebSocket streaming, ~1.6s P99 latency) ---
    # gpt-4o-transcribe: multilingual, fast, uses existing OPENAI_API_KEY.
    # turn_detection=False → use local SileroVAD instead of server VAD.
    # noise_reduction="near_field" → kiosk mic is close to speaker.
    stt = OpenAIRealtimeSTTService(
        api_key=openai_api_key,
        model="gpt-4o-transcribe",
        noise_reduction="near_field",
    )

    # --- LLM (OpenAI GPT-4o) ---
    llm = OpenAILLMService(
        api_key=openai_api_key,
        model="gpt-4o",
    )

    # --- TTS (Fish Speech, local server) ---
    # temperature=0.8 for more expressive/varied intonation
    tts = FishSpeechTTSService(
        base_url=fish_url,
        reference_id=fish_ref,
        temperature=0.8,
        top_p=0.8,
    )

    # --- Simli face (takes TTS audio -> returns lip-synced video + audio) ---
    # max_idle_time=120: Simli default is 30s — too short, kills avatar mid-pause.
    # 120s allows long silences without Simli disconnecting server-side.
    simli = SimliVideoService(
        api_key=simli_api_key,
        face_id=simli_face_id,
        params=SimliVideoService.InputParams(max_idle_time=120),
    )

    # --- Context aggregator ---
    context = OpenAILLMContext()
    context_aggregator = llm.create_context_aggregator(context)

    # --- Transcript processors (broadcast text to frontend) ---
    user_transcript = TranscriptProcessor(role="user")
    bot_transcript = TranscriptProcessor(role="bot")

    # --- Pipeline ---
    # audio in -> STT -> [user transcript] -> LLM -> [bot transcript] -> TTS -> Simli -> out
    pipeline = Pipeline([
        transport.input(),
        stt,
        user_transcript,
        context_aggregator.user(),
        llm,
        bot_transcript,
        tts,
        simli,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    # --- Flow Manager ---
    flow_manager = FlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
        tts=tts,
    )

    return task, transport, flow_manager
