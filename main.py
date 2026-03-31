"""
Hybrid Random Number Generator — FastAPI Dashboard Backend.

Usage:
    # Simulator mode (default, no hardware needed):
    uvicorn main:app --host 0.0.0.0 --port 8000

    # Serial mode (connect Pico first):
    SERIAL_PORT=COM3 uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os
import asyncio
import json
import logging
from collections import defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from stats_tests import run_all_tests
from serial_reader import SerialReader

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────

SERIAL_PORT = os.environ.get("SERIAL_PORT", "COM5")
BAUD_RATE = int(os.environ.get("BAUD_RATE", "115200"))
BUFFER_SIZE = 500         # how many values to keep per mode for analysis
STATS_INTERVAL = 10       # recalculate stats every N values
BROADCAST_BATCH = 5       # send data to frontend every N values

# ── App Setup ─────────────────────────────────────────────────────────────

app = FastAPI(title="Hybrid RNG Dashboard")

# Serve static files (HTML/CSS/JS)
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ── State ─────────────────────────────────────────────────────────────────

# Per-mode data buffers
buffers: dict[str, list[int]] = defaultdict(list)

# Per-mode latest stats
latest_stats: dict[str, list[dict]] = {}

# Connected WebSocket clients
clients: list[WebSocket] = []

# Data source (simulator or serial reader)
source = None


# ── Models ────────────────────────────────────────────────────────────────

class ModeSwitch(BaseModel):
    mode: str


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Serve the dashboard page."""
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/stats/{mode}")
async def get_stats(mode: str):
    """Return latest statistical test results for the given mode."""
    mode = mode.upper()
    if mode in latest_stats:
        return {"mode": mode, "tests": latest_stats[mode]}
    return {"mode": mode, "tests": []}


@app.get("/api/comparison")
async def get_comparison():
    """Return statistical results for all three modes side-by-side."""
    result = {}
    for m in ("TRNG", "PRNG", "HYBRID"):
        result[m] = {
            "count": len(buffers.get(m, [])),
            "tests": latest_stats.get(m, []),
        }
    return result


@app.post("/api/mode")
async def switch_mode(body: ModeSwitch):
    """Switch the active generation mode."""
    mode = body.mode.upper()
    if mode not in ("TRNG", "PRNG", "HYBRID"):
        return {"error": "Invalid mode. Use TRNG, PRNG, or HYBRID."}

    if source and hasattr(source, "set_mode"):
        source.set_mode(mode)

    # Notify all clients of mode switch
    msg = json.dumps({"type": "mode_change", "mode": mode})
    for ws in list(clients):
        try:
            await ws.send_text(msg)
        except Exception:
            pass

    return {"status": "ok", "mode": mode}


@app.get("/api/buffer/{mode}")
async def get_buffer(mode: str):
    """Return raw buffer data for a mode (useful for debugging)."""
    mode = mode.upper()
    return {"mode": mode, "data": buffers.get(mode, [])[-200:]}


# ── WebSocket ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    logger.info("WebSocket client connected (%d total)", len(clients))
    try:
        while True:
            # Keep connection alive; client may send commands
            data = await ws.receive_text()
            # Optionally handle commands from client
            try:
                msg = json.loads(data)
                if msg.get("type") == "switch_mode":
                    if source and hasattr(source, "set_mode"):
                        source.set_mode(msg["mode"].upper())
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        if ws in clients:
            clients.remove(ws)
        logger.info("WebSocket client disconnected (%d total)", len(clients))


# ── Background Data Pump ──────────────────────────────────────────────────

async def broadcast(message: dict):
    """Send a JSON message to all connected WebSocket clients."""
    text = json.dumps(message)
    for ws in list(clients):
        try:
            await ws.send_text(text)
        except Exception:
            if ws in clients:
                clients.remove(ws)


async def data_pump():
    """Read values from Pico serial, buffer them, compute stats, and broadcast."""
    global source
    batch = []
    count = 0

    # Always use serial reader — reads directly from Raspberry Pi Pico
    source = SerialReader(port=SERIAL_PORT, baud_rate=BAUD_RATE)
    logger.info("Connecting to Pico on %s at %d baud", SERIAL_PORT, BAUD_RATE)

    async for mode, value in source.read_values():
        # Buffer the value under its mode
        buf = buffers[mode]
        buf.append(value)
        if len(buf) > BUFFER_SIZE:
            buffers[mode] = buf[-BUFFER_SIZE:]

        batch.append({"mode": mode, "value": value})
        count += 1

        # Broadcast in batches
        if len(batch) >= BROADCAST_BATCH:
            await broadcast({"type": "data", "values": batch})
            batch = []

        # Recalculate stats periodically
        if count % STATS_INTERVAL == 0 and len(buffers[mode]) >= 20:
            try:
                stats = run_all_tests(buffers[mode])
                latest_stats[mode] = stats
                logger.info("Stats computed for %s (%d samples)", mode, len(buffers[mode]))
                await broadcast({
                    "type": "stats",
                    "mode": mode,
                    "tests": stats,
                    "count": len(buffers[mode]),
                })
            except Exception as exc:
                logger.error("Stats error for %s: %s", mode, exc)


@app.on_event("startup")
async def startup():
    """Launch the background data pump."""
    asyncio.create_task(data_pump())
