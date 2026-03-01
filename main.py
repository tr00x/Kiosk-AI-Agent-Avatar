"""Entry point for the Dental Clinic Kiosk.

- Serves index.html on port 8080
- WebRTC signaling via /api/offer and /api/ice-candidate
- WebSocket on ws://localhost:8080/events broadcasts UI events
- Session management: one session at a time, 60s silence timeout
- Flow gating: greeting fires on WebRTC connect (after 2s); avatar video starts once TTS audio arrives
"""

import asyncio
import json
import logging
import os
import sys

from aiohttp import web
from loguru import logger
from dotenv import load_dotenv

# Route Simli's stdlib logger through loguru so we see its errors
logging.getLogger("simli_client").addHandler(logging.StreamHandler(sys.stderr))
logging.getLogger("simli_client").setLevel(logging.DEBUG)

from pipecat.pipeline.base_task import PipelineTaskParams
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCRequestHandler,
    SmallWebRTCRequest,
    SmallWebRTCPatchRequest,
)

from tools import set_broadcast_fn, search_patient_today  # checkin_appointment disabled for now
from flow import create_greeting_node
from agent import create_agent

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
ws_clients: set[web.WebSocketResponse] = set()
session_active = False
silence_timer_task: asyncio.Task | None = None
current_pipeline_task = None
current_flow_manager = None
current_transport = None

_flow_initialized = False

SILENCE_TIMEOUT_SECS = 60
PORT = 8080

# SmallWebRTC signaling handler
webrtc_handler = SmallWebRTCRequestHandler()


# ---------------------------------------------------------------------------
# Flow init gate — ensures greeting only plays once
# ---------------------------------------------------------------------------
async def initialize_flow_if_needed():
    """Start the conversation only once."""
    global _flow_initialized
    if _flow_initialized or not current_flow_manager or not session_active:
        return
    _flow_initialized = True
    logger.info("Initializing conversation flow")
    await current_flow_manager.initialize(create_greeting_node())


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------
async def broadcast(message: str):
    """Send a message to all connected WebSocket clients."""
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_str(message)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def broadcast_event(event: str, data=None):
    """Broadcast a typed event. Also resets silence timer on any activity."""
    msg = {"event": event}
    if data is not None:
        msg["data"] = data
    await broadcast(json.dumps(msg))
    if session_active and event not in ("session_ended", "session_timeout"):
        reset_silence_timer()


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------
async def end_session(reason: str = "ended"):
    """Cleanly end the current session."""
    global session_active, silence_timer_task, current_pipeline_task
    global current_flow_manager, current_transport, _flow_initialized

    if not session_active:
        return

    logger.info(f"Ending session: {reason}")
    session_active = False
    _flow_initialized = False

    if silence_timer_task and not silence_timer_task.done():
        silence_timer_task.cancel()
        silence_timer_task = None

    if current_pipeline_task:
        try:
            logger.info("Cancelling pipeline (will close Simli + WebRTC)...")
            await current_pipeline_task.cancel()
            logger.info("Pipeline cancelled — Simli session closed")
        except Exception as e:
            logger.error(f"Error cancelling pipeline: {e}")
        current_pipeline_task = None

    current_flow_manager = None
    current_transport = None

    await broadcast_event("session_ended")
    logger.info("Session ended. Ready for next connection.")


async def silence_timeout_handler():
    """Wait for SILENCE_TIMEOUT_SECS and end the session."""
    try:
        await asyncio.sleep(SILENCE_TIMEOUT_SECS)
        logger.info("Silence timeout reached")
        await broadcast_event("session_timeout")
        await end_session("silence_timeout")
    except asyncio.CancelledError:
        pass


def reset_silence_timer():
    """Reset the silence timeout countdown."""
    global silence_timer_task
    if silence_timer_task and not silence_timer_task.done():
        silence_timer_task.cancel()
    silence_timer_task = asyncio.create_task(silence_timeout_handler())


# ---------------------------------------------------------------------------
# Start a new session (called when WebRTC connection is established)
# ---------------------------------------------------------------------------
async def start_session(webrtc_connection):
    """Create the pipecat pipeline and start it with the WebRTC connection."""
    global session_active, current_pipeline_task, current_flow_manager
    global current_transport, _flow_initialized

    if session_active:
        await broadcast_event("busy")
        return

    session_active = True
    _flow_initialized = False
    logger.info("Starting new session...")

    try:
        task, transport, flow_manager = await create_agent(webrtc_connection)
        current_pipeline_task = task
        current_transport = transport
        current_flow_manager = flow_manager

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, participant):
            logger.info(f"Client connected: {participant}")
            await broadcast_event("call_started")
            reset_silence_timer()
            # Small delay for transport to stabilize, then start conversation.
            # Greeting TTS audio is what unblocks Simli's video consumer —
            # avatar video and greeting arrive at the browser roughly together.
            await asyncio.sleep(2)
            await initialize_flow_if_needed()

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, participant):
            logger.info(f"Client disconnected: {participant}")
            await end_session("client_disconnected")

        # Run pipeline in background
        asyncio.create_task(run_pipeline(task))

    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        session_active = False
        await broadcast_event("avatar_error", {"message": str(e)})


async def run_pipeline(task):
    """Run the pipeline task and handle completion."""
    try:
        params = PipelineTaskParams(loop=asyncio.get_running_loop())
        await task.run(params)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        # Only end session if this task is still the active one.
        # Prevents a stale task from killing a newer session.
        if current_pipeline_task is task:
            await end_session("pipeline_ended")


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

async def handle_index(request: web.Request) -> web.Response:
    """Serve the kiosk frontend."""
    return web.FileResponse(os.path.join(_BASE_DIR, "index.html"))


async def handle_offer(request: web.Request) -> web.Response:
    """WebRTC signaling: receive SDP offer, return SDP answer."""
    try:
        req_data = await request.json()
        webrtc_request = SmallWebRTCRequest.from_dict(req_data)

        async def on_connection(connection):
            await start_session(connection)

        answer = await asyncio.wait_for(
            webrtc_handler.handle_web_request(
                request=webrtc_request,
                webrtc_connection_callback=on_connection,
            ),
            timeout=15,
        )
        if answer:
            return web.json_response(answer)
        return web.json_response({"error": "No answer"}, status=500)
    except asyncio.TimeoutError:
        logger.error("Offer timed out after 15s")
        return web.json_response({"error": "Connection timed out"}, status=504)
    except Exception as e:
        logger.error(f"Offer error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_ice_candidate(request: web.Request) -> web.Response:
    """WebRTC signaling: receive ICE candidate."""
    try:
        req_data = await request.json()
        patch_request = SmallWebRTCPatchRequest(
            pc_id=req_data["pc_id"],
            candidates=req_data.get("candidates", []),
        )
        await webrtc_handler.handle_patch_request(patch_request)
        return web.json_response({"status": "ok"})
    except Exception as e:
        logger.error(f"ICE candidate error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for UI events."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    logger.info(f"WebSocket client connected (total: {len(ws_clients)})")

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    cmd = data.get("command")
                    if cmd == "end_session":
                        await end_session("user_stopped")
                    elif cmd == "video_ready":
                        await initialize_flow_if_needed()
                    elif cmd == "manual_search":
                        try:
                            result = search_patient_today(
                                data.get("last_name", ""),
                                data.get("dob"),
                            )
                            await ws.send_str(json.dumps({
                                "event": "manual_search_results",
                                "data": result,
                            }))
                        except Exception as e:
                            await ws.send_str(json.dumps({
                                "event": "manual_search_results",
                                "data": {"error": str(e), "results": []},
                            }))
                    # manual_checkin disabled for now — read-only mode
                    elif cmd == "speech_activity":
                        reset_silence_timer()
                except json.JSONDecodeError:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {ws.exception()}")
    finally:
        ws_clients.discard(ws)
        logger.info(f"WebSocket client disconnected (total: {len(ws_clients)})")

    return ws


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
async def on_startup(app: web.Application):
    """Initialize on startup."""

    async def broadcast_and_reset_timer(message: str):
        """Broadcast to WebSocket clients and reset silence timer on activity."""
        await broadcast(message)
        if session_active:
            reset_silence_timer()

    set_broadcast_fn(broadcast_and_reset_timer)
    logger.info(f"Kiosk running at http://localhost:{PORT} (idle, no session)")


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint for monitoring."""
    health = {"status": "ok", "session_active": session_active}
    try:
        from db import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health["database"] = "connected"
    except Exception as e:
        health["database"] = f"error: {e}"
        health["status"] = "degraded"
    return web.json_response(health)


async def on_shutdown(app: web.Application):
    """Cleanup on shutdown — give active session time to finish."""
    if session_active:
        logger.info("Shutdown requested — giving active session 10s to finish...")
        await broadcast_event("session_ended")
        try:
            await asyncio.wait_for(end_session("shutdown"), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Session didn't finish in time, forcing shutdown")
            await end_session("forced_shutdown")
    for ws in set(ws_clients):
        await ws.close()


def main():
    load_dotenv()

    # Enable DEBUG for pipecat_flows to see function registration/transitions
    logger.enable("pipecat_flows")

    required = ["OPENAI_API_KEY", "SIMLI_API_KEY", "SIMLI_FACE_ID"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/", handle_index)
    app.router.add_get("/logo.jpg", lambda r: web.FileResponse(os.path.join(_BASE_DIR, "logo.jpg")))
    app.router.add_get("/idle-avatar.mp4", lambda r: web.FileResponse(
        os.path.join(_BASE_DIR, "f0ba4efe-7946-45de-9955-c04a04c367b9.mp4"),
        headers={"Cache-Control": "public, max-age=86400"},
    ))
    app.router.add_post("/api/offer", handle_offer)
    app.router.add_post("/api/ice-candidate", handle_ice_candidate)
    app.router.add_get("/events", handle_ws)
    app.router.add_get("/health", handle_health)

    print(f"\n  Dental Clinic Kiosk (Simli)")
    print(f"  Open http://localhost:{PORT} in your browser\n")

    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
