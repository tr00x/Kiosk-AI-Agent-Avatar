"""Console voice test — talk to the dental bot via mic/speaker, no Tavus avatar."""

import asyncio
import os
from dotenv import load_dotenv
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.base_task import PipelineTaskParams
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext

from pipecat_flows import FlowManager
from flow import create_greeting_node


async def main():
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY", "")

    # --- Local audio transport (mic + speaker) ---
    transport = LocalAudioTransport(
        params=LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                confidence=0.5,
                start_secs=0.5,
                stop_secs=1.5,
                min_volume=0.5,
            )),
        )
    )

    # --- STT (faster-whisper, local) ---
    stt = WhisperSTTService(
        model=Model.BASE,
        device="cpu",
        compute_type="default",
        language="en",
        no_speech_prob=0.4,
    )

    # --- LLM ---
    llm = OpenAILLMService(
        api_key=openai_api_key,
        model="gpt-4o",
    )

    # --- TTS (Kokoro, local) ---
    tts = KokoroTTSService(voice_id="af_heart")

    # --- Context ---
    context = OpenAILLMContext()
    context_aggregator = llm.create_context_aggregator(context)

    # --- Pipeline ---
    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=False,
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

    # Start the flow when transport is ready
    @transport.event_handler("on_client_connected")
    async def on_connected(transport, participant):
        logger.info("Audio ready — initializing flow")
        await flow_manager.initialize(create_greeting_node())

    logger.info("Starting voice test — speak into your mic (Ctrl+C to stop)")
    params = PipelineTaskParams(loop=asyncio.get_running_loop())
    await task.run(params)


if __name__ == "__main__":
    asyncio.run(main())
