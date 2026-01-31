import asyncio
import websockets
# import pyaudio
import wave

async def test_bot():
    uri = "ws://localhost:8000/ws"
    
    async with websockets.connect(uri) as websocket:
        print("Connected to bot!")
        
        # You can send audio data here
        # For now, just receive responses
        async for message in websocket:
            print(f"Received: {len(message)} bytes")
            # Save or play the audio response

asyncio.run(test_bot())