"""
Simple test server for local Pipecat bot testing
Run this to test your bot without Plivo
"""

import asyncio
import os
from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv
import uvicorn
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

# Import the run_bot function from your final bot
from main import run_bot

load_dotenv()

app = FastAPI(title="Pipecat Test Server")


@app.get("/")
async def root():
    return {
        "message": "Pipecat Bot Test Server Running",
        "websocket_endpoint": "/ws",
        "status": "ready"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for testing the bot"""
    await websocket.accept()
    logger.info("Client connected to test server")
    
    try:
        # Create transport without Plivo serializer for local testing
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=True,  # Enable WAV headers for easier testing
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(
                        stop_secs=0.2,
                    )
                ),
            ),
        )
        
        # Run the bot
        await run_bot(transport, handle_sigint=False)
        
    except Exception as e:
        logger.error(f"Error in websocket connection: {e}")
        await websocket.close()
    finally:
        logger.info("Client disconnected from test server")


if __name__ == "__main__":
    # Check for required environment variables
    required_vars = ["OPENAI_API_KEY", "DEEPGRAM_API_KEY", "CARTESIA_API_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set them in your .env file")
        exit(1)
    
    logger.info("Starting Pipecat test server...")
    logger.info("WebSocket endpoint: ws://localhost:8000/ws")
    logger.info("Press Ctrl+C to stop")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )