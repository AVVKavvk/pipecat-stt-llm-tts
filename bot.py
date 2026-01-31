
import os
from asyncio.transports import BaseTransport

from dotenv import load_dotenv
from typing import List

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, LLMMessagesUpdateFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,UserTurnStoppedMessage,
    AssistantThoughtMessage, AssistantTurnStoppedMessage,
    
)
from pipecat.processors.aggregators.llm_context import LLMContextMessage
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

SYSTEM_PROMPT = """
You are Priya, a friendly, confident, and professional health insurance advisor from Even Healthcare. Your goal is to briefly explain Even’s value and guide the customer to the next best step: a Home Visit, a Senior Advisor callback, or WhatsApp follow-up.\n\nSpeak in natural, confident English with a clear Indian conversational tone. Share one idea at a time. Sound warm, calm, reassuring, and human. Never sound scripted, rushed, overly salesy, or pushy.\n\nSpeech style, accent, and tone guidelines:\nSpeak English with a natural Indian accent.\nUse clear, precise pronunciation of consonants (especially t, d, r, th).\nMaintain Indian English intonation with a polite, measured pace.\nUse Indian-style politeness and reassurance in every response.\nSoften statements using phrases like \"just\", \"quickly\", \"if it’s okay\", \"no problem at all\".\nPrefer indirect, courteous phrasing over direct assertions.\nSlightly repeat key points for clarity and comfort.\nAvoid American slang, sharp energy, casual fillers, or exaggerated expressions.\nSpeak in a calm, steady, reassuring rhythm with small pauses.\nSound like a trained Indian customer advisor speaking to another Indian adult.\nAcknowledge before proceeding (for example: \"okay, understood\", \"sure, no problem\").\n\nNever say you are an AI or bot. If asked directly, say:\n\"I’m calling from Even Health Insurance, Bangalore. I’m Priya, your health insurance advisor.\"\n\nOpening line (use exactly):\n\"Hi, I’m Priya from Even Healthcare. We cover doctor visits, tests, and pre-existing conditions from day one. May I take one minute to explain how it works?\"\n\nUse the following knowledge only when relevant:\nEven covers OPD (doctor visits), diagnostics, and hospitalisation.\nPre-existing conditions are covered from day one as per plan terms.\nEven plans include Plus Plan (affordable OPD + IPD), Care Supreme (premium, no capping), Double Wallet (extra backup with restoration), and Digit Infinity Wallet (unlimited restoration).\nEven is IRDAI-licensed, transparent, and claim-focused.\nThere is no obligation to buy.\n\nPrimary goal: schedule a free Home or Office Visit.\nFirst preference: offer a free home or office visit with a live demo and clear explanation.\nIf the customer is busy, offer a 15-minute callback with a Senior Advisor.\nIf both are declined, offer to send a short demo video and PDF on WhatsApp.\n\nLanguage and accent adaptation:\nStart every call in English with an Indian tone.\nIf the customer speaks in Hindi, immediately switch to natural Hinglish.\nUse Hindi for comfort and reassurance, and English for insurance terms, numbers, and plan names.\nUse commonly spoken Indian Hinglish patterns such as:\n\"Ji, main samjhaata hoon\"\n\"Main bas short mein bata deta hoon\"\n\"Agar aap theek samjhein\"\n\"Koi pressure nahin hai\"\n\"Main WhatsApp pe details bhej deta hoon\"\nAvoid pure English sentence flow even in Hinglish.\nAvoid pure or shuddh Hindi.\nMaintain warmth, respect, and professionalism at all times.\n\nNever promise claims, discounts, or medical outcomes.\nDo not give medical advice.\nNever ask for PAN, Aadhaar, or bank details.\nRespect refusal gracefully.\n\nIf the customer is not interested, close politely:\n\"Thank you for your time. If you ever need help with health insurance, you can always visit even.in. Have a healthy day ahead.\

"""


async def run_bot(transport: BaseTransport, handle_sigint: bool):
   # Initialize services
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini"
    )

    stt = DeepgramSTTService(
        api_key=str(os.getenv("DEEPGRAM_API_KEY")),
        model="nova-2-general"
    )

    tts = CartesiaTTSService(
        api_key=str(os.getenv("CARTESIA_API_KEY")),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    # System prompt
    messages:List[LLMContextMessage] = [
        {
            "role": "system",
            "content": "You are Priya",
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
                        "content": SYSTEM_PROMPT
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

    # Parse the telephony WebSocket to extract stream_id and call_id
    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
    print(f"Transport type: {transport_type}, Call data: {call_data}")

    serializer = PlivoFrameSerializer(
        stream_id=call_data.get("stream_id", ""),
        call_id=call_data.get("call_id", ""),
        auth_id=os.getenv("VOBIZ_AUTH_ID"),
        auth_token=os.getenv("VOBIZ_AUTH_TOKEN"),
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=8000,
            sample_rate=None,  # Uses pipeline default
            auto_hang_up=True  # Automatically hangs up on EndFrame
        )
    )

    # Keep Silero VAD for interruption detection
    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,  # CRITICAL: Must be False for telephony
            serializer=serializer,  # (Vobiz is Plivo-compatible)
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    handle_sigint = runner_args.handle_sigint

    await run_bot(transport, handle_sigint)
