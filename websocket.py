from fastapi import WebSocket, Request
import json, base64
import os
from dotenv import load_dotenv

load_dotenv()


def get_host_and_protocol(request: Request):
    public_url = os.getenv("URL")

    if public_url:
        if public_url.startswith("https://"):
            protocol = "https"
            host = public_url.replace("https://", "").rstrip("/")
        elif public_url.startswith("http://"):
            protocol = "http"
            host = public_url.replace("http://", "").rstrip("/")
        else:
            protocol = "https"
            host = public_url.rstrip("/")
        print(f"[INFO] PUBLIC_URL: {public_url}, Extracted - Host: {host}, Protocol: {protocol}")
        return host, protocol
    else:
        if request is None:
            raise ValueError("Request object required when PUBLIC_URL is not set")
        host = request.headers.get("host")
        if not host:
            raise ValueError("Cannot determine server host from request headers")

        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto:
            protocol = forwarded_proto
        else:
            protocol = (
                "http"
                if host.startswith("localhost") or host.startswith("127.0.0.1")
                else "https"
            )

        print(f"[DEBUG] Detected protocol: {protocol}")
        return host, protocol


def get_vobiz_websocket_url(host: str):
    return f"wss://{host}/stream"


async def handle_vobiz_websocket(
    websocket: WebSocket,
    path: str,
    body: str,
    serviceHost: str
):
    """Common handler for Vobiz WebSocket connections on any path."""
    print(f"[DEBUG] WebSocket connection attempt on path: {path}, Query params body: {body}, serviceHost: {serviceHost}")
    print(f"[DEBUG] Client: {websocket.client}, Headers: {dict(websocket.headers)}")

    try:
        await websocket.accept()
        print("[SUCCESS] WebSocket connection accepted for Vobiz call")
    except Exception as e:
        print(f"[ERROR] Failed to accept WebSocket connection: {e}")
        raise

    body_data = {}
    if body:
        try:
            decoded_json = base64.b64decode(body).decode("utf-8")
            body_data = json.loads(decoded_json)
            print(f"Decoded body data: {body_data}")
        except Exception as e:
            print(f"Error decoding body parameter: {e}")
    else:
        print("No body parameter received")

    try:
        from bot import bot
        from pipecat.runner.types import WebSocketRunnerArguments

        print("[DEBUG] Starting bot initialization...")

        # Create runner arguments and run the bot
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        runner_args.handle_sigint = False

        print("[DEBUG] Calling bot function...")
        await bot(runner_args)

        print("[DEBUG] Bot function completed")

    except Exception as e:
        print(f"[ERROR] Error in WebSocket endpoint: {e}")
        import traceback
        print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
        try:
            await websocket.close()
        except:
            pass
