from __future__ import annotations


from fastapi import FastAPI, Form, WebSocket, Query, HTTPException, Request
import websocket
from fastapi.responses import JSONResponse, HTMLResponse
import httpx
import json
import urllib.parse
import os
from dotenv import load_dotenv

load_dotenv()

import base64
FastAPI(title="Voice Sandwich (Gemini)")

app=FastAPI()

@app.post("/vobiz/outbound-call")
async def vobiz_outbound_call(request: Request) -> JSONResponse:
    print(f"[Vobiz] outbound call api is triggered")

    try:
        data = await request.json()
        if not data.get("from_number") or not data.get("to_number"):
            raise HTTPException(
                status_code=400,
                detail="Missing 'phone_number' or 'to_number' in the request body",
            )
        from_number = data.get("from_number")
        to_number = data.get("to_number")
        body_data = data.get("body", {})
        print(f"\n[DEBUG] Body data: {body_data}")

        host, protocol = websocket.get_host_and_protocol(request)
        answer_url = f"{protocol}://{host}/answer"
        if body_data:
            body_json = json.dumps(body_data)
            body_encoded = urllib.parse.quote(body_json)
            answer_url = f"{answer_url}?body_data={body_encoded}"

        print(f"[INFO] Answer URL that will be sent to Vobiz: {answer_url}")

        url = f"https://api.vobiz.ai/api/v1/Account/{os.getenv("VOBIZ_AUTH_ID")}/Call/"
        headers = {
            "X-Auth-ID": os.getenv("VOBIZ_AUTH_ID"),
            "X-Auth-Token": os.getenv("VOBIZ_AUTH_TOKEN"),
            "Content-Type": "application/json",
        }
        body = {
            "from": from_number,
            "to": to_number,
            "answer_url": answer_url,
            "answer_method": "POST",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=body)

        if resp.status_code != 201:
            print(
                f"[ERROR] Vobiz API call failed with status {resp.status_code} : {resp.text}"
            )
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Vobiz API error: {resp.text}",
            )

        print(f"[SUCCESS] Vobiz API call successful!")
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": resp.json(),
            },
        )

    except HTTPException:
        raise

    except httpx.RequestError as exc:
        print(f"[ERROR] HTTPX request error: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Vobiz API request failed: {str(exc)}",
        )

    except Exception as exc:
        print(f"[ERROR] Unexpected error in outbound call: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while initiating outbound call",
        )


@app.api_route("/incoming-call", methods=["POST"])
async def vobiz_answer(
    request: Request,
    body_data: str = Form(None)
) -> HTMLResponse:
    print("Serving answer XML for vobiz call")

    form_data = await request.form()
    print(f"[DEBUG] Full Form Data received: {dict(form_data)}")
    parsed_body_data = {}
    if body_data:
        try:
            parsed_body_data = json.loads(body_data)
        except json.JSONDecodeError:
            print(f"Failed to parse body data: {body_data}")

    try:
        host, protocol = websocket.get_host_and_protocol(request)
        base_ws_url = websocket.get_vobiz_websocket_url(host)
        query_params = []

        if parsed_body_data:
            body_json = json.dumps(parsed_body_data)
            body_encoded = base64.b64encode(body_json.encode("utf-8")).decode("utf-8")
            query_params.append(f"body={body_encoded}")

        if query_params:
            ws_url = f"{base_ws_url}?{'&amp;'.join(query_params)}"
        else:
            ws_url = base_ws_url
        print(
            f"[INFO] WebSocket URL being sent to Vobiz: {ws_url}, Host: {host}"
        )

        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Stream 
                    bidirectional="true" 
                    keepCallAlive="true" 
                    contentType="audio/x-mulaw;rate=8000">
                    {ws_url}
                </Stream>
            </Response>
            """

        print(f"Answer Url is hit")
        return HTMLResponse(content=xml_content, media_type="application/xml")

    except Exception as e:
        print(f"Error generating answer XML: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate XML: {str(e)}")


@app.websocket("/stream")
async def websocket_stream(
    socket: WebSocket,
    body: str = Query(None),
    serviceHost: str = Query(None),
):
    """Handle WebSocket connection at /stream path."""
    await websocket.handle_vobiz_websocket(socket, "/stream", body, serviceHost)




@app.get("/health")
def health():
    return {"ok": True}


@app.post("/hangup")
async def hangup(request: Request):
    try:
        # Parse the form data into a dictionary
        form_data = await request.form()
        body = dict(form_data)
        
        print("Hangup called")
        print(body)
        
        return {"status": "received"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to hangup: {str(e)}")






