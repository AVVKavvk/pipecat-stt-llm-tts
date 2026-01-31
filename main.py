#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
from asyncio.transports import BaseTransport

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, LLMMessagesUpdateFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,UserTurnStoppedMessage,
    AssistantThoughtMessage, AssistantTurnStoppedMessage
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

load_dotenv()


async def run_bot(transport: BaseTransport, handle_sigint: bool):
    # Initialize services
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini"
    )

    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        model="nova-2-general"
    )

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    # System prompt
    messages = [
        {
            "role": "system",
            "content": "You are an elementary teacher in an audio call. Your output will be converted to audio so don't include special characters in your answers. Respond to what the student said in a short sentence.",
        },
    ]

    # Create context using the universal LLMContext
    context = LLMContext(messages)
    
    # Create aggregators using the universal API
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    # Build pipeline
    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from client
            stt,  # Speech-To-Text
            user_aggregator,  # User context aggregator
            llm,  # LLM
            tts,  # Text-To-Speech
            transport.output(),  # Websocket output to client
            assistant_aggregator,  # Assistant context aggregator
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # Kick off the conversation with introduction
        await task.queue_frames([
            LLMMessagesUpdateFrame(
                messages=[
                    {
                        "role": "system",
                        "content": "Please introduce yourself to the user."
                    }
                ],
                run_llm=True
            )
        ])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.queue_frame(EndFrame())

    runner = PipelineRunner(handle_sigint=handle_sigint)
    
    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message: UserTurnStoppedMessage):
        timestamp = f"[{message.timestamp}] " if message.timestamp else ""
        line = f"{timestamp}user: {message.content}"
        print(f"Transcript: {line}")

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message: AssistantTurnStoppedMessage):
        timestamp = f"[{message.timestamp}] " if message.timestamp else ""
        line = f"{timestamp}assistant: {message.content}"
        print(f"Transcript: {line}")
        
    @assistant_aggregator.event_handler("on_assistant_thought")
    async def on_assistant_thought(aggregator, message: AssistantThoughtMessage):
        timestamp = f"[{message.timestamp}] " if message.timestamp else ""
        line = f"{timestamp}assistant: {message.content}"
        print(f"Thought: {line}")
        

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud."""

    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
    logger.info(f"Auto-detected transport: {transport_type}")

    # Initialize Plivo serializer
    serializer = PlivoFrameSerializer(
        stream_id=call_data["stream_id"],
        call_id=call_data["call_id"],
        auth_id=os.getenv("PLIVO_AUTH_ID", ""),
        auth_token=os.getenv("PLIVO_AUTH_TOKEN", ""),
    )

    # Create transport with VAD
    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    stop_secs=0.2,
                )
            ),
            serializer=serializer,
        ),
    )

    handle_sigint = runner_args.handle_sigint

    await run_bot(transport, handle_sigint)