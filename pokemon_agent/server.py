"""
Pokemon Agent — FastAPI Game Server

Provides HTTP + WebSocket API for controlling a Game Boy / GBA emulator
running a Pokemon ROM, reading game state, and broadcasting events.
"""

import asyncio
import base64
import io
import json
import re
import time
from functools import partial
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GameConfig(BaseModel):
    """Server configuration — set before startup."""
    rom_path: str
    game_type: str = "auto"       # "red", "firered", or "auto"
    port: int = 8765
    data_dir: str = "~/.pokemon-agent"
    load_state: Optional[str] = None  # Save-state name to auto-load on startup


class ActionRequest(BaseModel):
    """Body for POST /action."""
    actions: list[str]


class SaveRequest(BaseModel):
    """Body for POST /save and POST /load."""
    name: str


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_config: Optional[GameConfig] = None
_emulator = None          # Emulator instance
_reader = None            # GameMemoryReader subclass instance
_start_time: float = 0.0
_loop: Optional[asyncio.AbstractEventLoop] = None

# WebSocket clients
_ws_clients: Set[WebSocket] = set()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pokemon Agent Server",
    version=__version__,
    description="HTTP + WebSocket API for Pokemon emulator control",
)

# CORS — allow everything for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_game_type(rom_path: str) -> str:
    """Pick reader type based on file extension."""
    ext = Path(rom_path).suffix.lower()
    if ext in (".gb", ".gbc"):
        return "red"
    elif ext == ".gba":
        return "firered"
    raise ValueError(f"Unrecognised ROM extension: {ext}")


def _ensure_emulator():
    """Raise 503 if the emulator isn't ready."""
    if _emulator is None:
        raise HTTPException(status_code=503, detail="Emulator not initialised")


async def _run_sync(func, *args):
    """Run a blocking emulator call in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def broadcast(event: dict):
    """Send a JSON event to every connected WebSocket client."""
    dead: list[WebSocket] = []
    payload = json.dumps(event)
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


def _get_state_dict() -> dict:
    """Build full game state from the memory reader."""
    from pokemon_agent.state.builder import build_game_state
    return build_game_state(_reader)


def _get_screenshot_bytes() -> bytes:
    """Grab the current frame as PNG bytes."""
    screen = _emulator.get_screen()          # PIL Image or numpy array
    buf = io.BytesIO()
    # If it's a numpy array, convert to PIL first
    try:
        from PIL import Image
        if not isinstance(screen, Image.Image):
            import numpy as np
            screen = Image.fromarray(screen)
        screen.save(buf, format="PNG")
    except ImportError:
        # Fallback: assume screen already has save()
        screen.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Action parser
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(
    r"^(?P<kind>press|walk|hold|wait|a_until_dialog_end)(?:_(?P<rest>.+))?$"
)


async def _execute_action(action_str: str) -> None:
    """Parse and execute a single action string on the emulator.

    Supported formats:
        press_X       — press button X for 10 frames, wait 20 frames
        walk_X        — press direction for 16 frames, wait 8 frames
        hold_X_N      — hold button X for N frames
        wait_N        — tick N frames with no input
        a_until_dialog_end — press A every 30 frames until dialog clears (max 300)
    """
    action_str = action_str.strip().lower()

    if action_str == "a_until_dialog_end":
        for _ in range(10):  # max 300 frames = 10 * 30
            await _run_sync(_emulator.press, "a")
            await _run_sync(_emulator.tick, 30)
            # Check dialog flag via reader if available
            try:
                state = _get_state_dict()
                if not state.get("dialog_active", False):
                    break
            except Exception:
                pass
        return

    # Split into tokens
    parts = action_str.split("_")

    if parts[0] == "press" and len(parts) >= 2:
        button = "_".join(parts[1:])
        # Hold button for 8 frames so the game registers the press,
        # then wait 12 frames for the game to process it.
        await _run_sync(_emulator.press, button, 8)
        await _run_sync(_emulator.tick, 12)
        return

    if parts[0] == "walk" and len(parts) >= 2:
        direction = parts[1]
        # Gen 1 movement timing (empirically tested):
        #   - Button must be held >= 4 frames for the game's vblank joypad
        #     poll to register the input reliably.
        #   - wWalkCounter starts at 8, decrements each frame (2 px/frame
        #     = 16 px = 1 tile). Total walk animation = ~16 frames.
        #   - Minimum total frames for a confirmed tile move = 17.
        #   - We use hold=8 + wait=12 = 20 total for a safety margin.
        await _run_sync(_emulator.press, direction, 8)
        await _run_sync(_emulator.tick, 12)
        return

    if parts[0] == "hold" and len(parts) >= 3:
        button = "_".join(parts[1:-1])
        frames = int(parts[-1])
        await _run_sync(_emulator.press, button, frames)
        return

    if parts[0] == "wait" and len(parts) == 2:
        frames = int(parts[1])
        await _run_sync(_emulator.tick, frames)
        return

    raise ValueError(f"Unknown action format: {action_str}")


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def configure(config: GameConfig):
    """Set server configuration (call before app startup)."""
    global _config
    _config = config


@app.on_event("startup")
async def _startup():
    global _emulator, _reader, _start_time, _config, _loop
    _loop = asyncio.get_running_loop()
    _start_time = time.time()

    if _config is None:
        # Config can be injected via environment or set beforehand
        print("[server] WARNING: No GameConfig set — emulator will NOT start.")
        print("[server] Call server.configure(GameConfig(...)) before startup.")
        return

    rom = Path(_config.rom_path).expanduser().resolve()
    if not rom.exists():
        print(f"[server] ERROR: ROM not found: {rom}")
        return

    # Auto-detect game type
    game_type = _config.game_type
    if game_type == "auto":
        game_type = _detect_game_type(str(rom))

    print(f"[server] Loading ROM: {rom}")
    print(f"[server] Detected game type: {game_type}")

    # Create emulator
    from pokemon_agent.emulator import create_emulator
    _emulator = create_emulator(str(rom))

    # Create memory reader
    if game_type == "red":
        from pokemon_agent.memory.red import PokemonRedReader
        _reader = PokemonRedReader(_emulator)
    elif game_type == "firered":
        from pokemon_agent.memory.firered import PokemonFireRedReader
        _reader = PokemonFireRedReader(_emulator)
    else:
        raise ValueError(f"Unknown game type: {game_type}")

    # Create data directories
    data_dir = Path(_config.data_dir).expanduser().resolve()
    (data_dir / "saves").mkdir(parents=True, exist_ok=True)

    # Try mounting dashboard
    try:
        import pokemon_agent.dashboard as dashboard_mod  # noqa: F401
        from fastapi.staticfiles import StaticFiles
        dash_dir = Path(dashboard_mod.__file__).parent / "static"
        if dash_dir.is_dir():
            app.mount("/dashboard", StaticFiles(directory=str(dash_dir), html=True), name="dashboard")
            print(f"[server] Dashboard mounted at /dashboard")
        else:
            print("[server] Dashboard module found but no static/ directory")
    except ImportError:
        print("[server] Dashboard not installed — /dashboard unavailable")
        print("[server]   Install with: pip install pokemon-agent[dashboard]")

    # Auto-load a save state if specified
    if _config.load_state:
        saves_dir = data_dir / "saves"
        state_path = saves_dir / f"{_config.load_state}.state"
        if state_path.exists():
            try:
                _emulator.load_state(str(state_path))
                print(f"[server] Loaded save state: {_config.load_state}")
            except Exception as e:
                print(f"[server] WARNING: Failed to load state '{_config.load_state}': {e}")
        else:
            print(f"[server] WARNING: Save state not found: {state_path}")

    print(f"[server] Ready — listening on port {_config.port}")
    print(f"[server] Endpoints:")
    print(f"[server]   GET  /          — server info")
    print(f"[server]   GET  /state     — game state")
    print(f"[server]   GET  /screenshot — current frame (PNG)")
    print(f"[server]   POST /action    — execute actions")
    print(f"[server]   POST /save      — save state")
    print(f"[server]   POST /load      — load state")
    print(f"[server]   GET  /saves     — list saves")
    print(f"[server]   GET  /minimap   — ASCII minimap")
    print(f"[server]   GET  /health    — health check")
    print(f"[server]   WS   /ws        — live events")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    """Server info."""
    return {
        "name": "pokemon-agent",
        "version": __version__,
        "game": _config.game_type if _config else None,
        "rom": _config.rom_path if _config else None,
        "uptime_seconds": round(time.time() - _start_time, 1) if _start_time else 0,
        "emulator_ready": _emulator is not None,
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "emulator_ready": _emulator is not None}


@app.get("/state")
async def get_state():
    """Full game state JSON."""
    _ensure_emulator()
    try:
        state = await _run_sync(_get_state_dict)
        return JSONResponse(content=state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {e}")


@app.get("/screenshot")
async def screenshot():
    """Current emulator frame as PNG image."""
    _ensure_emulator()
    try:
        png_bytes = await _run_sync(_get_screenshot_bytes)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot error: {e}")


@app.get("/screenshot/base64")
async def screenshot_base64():
    """Current emulator frame as base64-encoded PNG in JSON."""
    _ensure_emulator()
    try:
        png_bytes = await _run_sync(_get_screenshot_bytes)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return {"image": b64, "format": "png"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot error: {e}")


@app.post("/action")
async def execute_actions(req: ActionRequest):
    """Execute a sequence of game actions."""
    _ensure_emulator()
    try:
        executed = 0
        for action_str in req.actions:
            await _execute_action(action_str)
            executed += 1

        state_after = await _run_sync(_get_state_dict)

        # Broadcast to WebSocket clients
        await broadcast({
            "type": "action",
            "actions": req.actions,
            "actions_executed": executed,
            "state_after": state_after,
        })

        return {
            "success": True,
            "actions_executed": executed,
            "state_after": state_after,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Action error: {e}")


@app.post("/save")
async def save_state(req: SaveRequest):
    """Save emulator state to disk."""
    _ensure_emulator()
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save_path = saves_dir / f"{req.name}.state"
        await _run_sync(_emulator.save_state, str(save_path))
        return {"success": True, "path": str(save_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save error: {e}")


@app.post("/load")
async def load_state(req: SaveRequest):
    """Load emulator state from disk."""
    _ensure_emulator()
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
        save_path = saves_dir / f"{req.name}.state"
        if not save_path.exists():
            raise HTTPException(status_code=404, detail=f"Save not found: {req.name}")
        await _run_sync(_emulator.load_state, str(save_path))
        state_after = await _run_sync(_get_state_dict)

        await broadcast({"type": "state_update", "reason": "load", "state": state_after})

        return {"success": True, "name": req.name, "state_after": state_after}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Load error: {e}")


@app.get("/saves")
async def list_saves():
    """List available save-state files."""
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
        if not saves_dir.exists():
            return {"saves": []}
        files = sorted(saves_dir.glob("*.state"))
        saves = [
            {
                "name": f.stem,
                "file": f.name,
                "size_bytes": f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
            for f in files
        ]
        return {"saves": saves}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing saves: {e}")


@app.get("/minimap")
async def minimap():
    """Simple ASCII minimap — current map name + player position."""
    _ensure_emulator()
    try:
        state = await _run_sync(_get_state_dict)
        map_info = state.get("map", {})
        player = state.get("player", {})
        map_name = map_info.get("map_name", "Unknown")
        pos = player.get("position", {})
        x = pos.get("x", "?")
        y = pos.get("y", "?")

        lines = [
            f"=== {map_name} ===",
            f"Player position: ({x}, {y})",
            "",
            "  N",
            "W + E",
            "  S",
        ]
        text = "\n".join(lines)
        return Response(content=text, media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Minimap error: {e}")


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Live event stream via WebSocket."""
    await ws.accept()
    _ws_clients.add(ws)
    try:
        # Send a welcome message
        await ws.send_json({
            "type": "connected",
            "version": __version__,
            "emulator_ready": _emulator is not None,
        })
        # Keep alive — wait for client messages (or disconnect)
        while True:
            data = await ws.receive_text()
            # Clients can send a "ping" to keep alive
            if data.strip().lower() == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Dashboard fallback
# ---------------------------------------------------------------------------

@app.get("/dashboard")
@app.get("/dashboard/{path:path}")
async def dashboard_fallback(path: str = ""):
    """Fallback when dashboard extra is not installed."""
    # If a real dashboard mount exists this route is shadowed, so this only
    # fires when the dashboard module is missing.
    raise HTTPException(
        status_code=404,
        detail="Dashboard not installed. Install with: pip install pokemon-agent[dashboard]",
    )
