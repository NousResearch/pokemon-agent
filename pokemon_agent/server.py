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


class EventRequest(BaseModel):
    """Body for POST /event — the agent pushes narration to the dashboard."""
    type: str                       # "reasoning" | "decision" | "key_moment" | "alert"
    text: Optional[str] = None      # for reasoning / decision / alert
    description: Optional[str] = None  # for key_moment
    category: Optional[str] = None     # key_moment category: milestone/badge/catch/alert


class SaveRequest(BaseModel):
    """Body for POST /save and POST /load."""
    name: str


class Objective(BaseModel):
    """A single objective shown on the dashboard."""
    tier: str            # "primary" | "secondary" | "tertiary"
    text: str
    done: bool = False


class ObjectivesRequest(BaseModel):
    """Body for POST /objectives — replace the full objective list."""
    objectives: list[Objective]


class ControlRequest(BaseModel):
    """Body for POST /control — set the autopilot run state."""
    state: str           # "running" | "paused" | "stopped"


class NewGameRequest(BaseModel):
    """Body for POST /games/new."""
    name: Optional[str] = None


class HermesSessionRequest(BaseModel):
    """Body for POST /games/{id}/hermes — bind the Hermes session id."""
    hermes_session_id: str


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_config: Optional[GameConfig] = None
_emulator = None          # Emulator instance
_reader = None            # GameMemoryReader subclass instance
_start_time: float = 0.0
_loop: Optional[asyncio.AbstractEventLoop] = None

# Dynamic objectives shown on the dashboard (default = Kanto opening goals).
_objectives: list = [
    {"tier": "primary", "text": "Deliver Oak's Parcel · get Pokédex", "done": False},
    {"tier": "secondary", "text": "Reach Pewter City · Boulder Badge", "done": False},
    {"tier": "tertiary", "text": "Catch a Grass/Electric type", "done": False},
]

# Autopilot run state. "stopped" (default) | "running" | "paused".
# A standalone `pokemon-agent play` loop reads this and only acts when running.
_control_state: str = "stopped"

# Game-session layer (binds Hermes brain + emulator saves + objectives/stats).
_session_mgr = None       # GameSessionManager
_active_session = None     # GameSession currently being played

# WebSocket clients
_ws_clients: Set[WebSocket] = set()

# Replay buffer — recent narration/milestone events so a client that connects
# mid-run sees the Field Log already populated instead of an empty panel.
# Only display-worthy events are kept (reasoning/decision/key_moment/alert/
# action), not the high-frequency screenshot/state_update frames.
from collections import deque
_event_history: deque = deque(maxlen=200)
_REPLAYABLE = {"reasoning", "decision", "thought", "key_moment", "moment", "alert", "battle", "action"}

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
    """Send a JSON event to every connected WebSocket client.

    Display-worthy events (narration, milestones, actions) are also recorded
    in a replay buffer so a client connecting mid-run can backfill the log.
    """
    etype = event.get("type")
    if etype in _REPLAYABLE:
        rec = dict(event)
        rec.setdefault("ts", time.time())
        if etype == "action":
            # Don't store the full state snapshot in the buffer — just the moves.
            rec.pop("state_after", None)
        _event_history.append(rec)

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
    state = build_game_state(_reader)
    # Attach the on-screen walkability grid for Red/Blue (overworld tilesets).
    # This is ground-truth collision read from RAM — far more reliable than
    # inferring walkability from pixels.
    try:
        if _config and _config.game_type == "red" and not (
            state.get("battle") or {}
        ).get("in_battle"):
            from pokemon_agent.collision import build_collision_grid, render_ascii_map
            col = build_collision_grid(_reader.emu)
            col["ascii"] = render_ascii_map(col, legend=True)
            state["collision"] = col
    except Exception as exc:  # noqa: BLE001
        state["collision_error"] = f"{type(exc).__name__}: {exc}"
    return state


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
        from pokemon_agent.memory.firered import FireRedMemoryReader
        _reader = FireRedMemoryReader(_emulator)
    else:
        raise ValueError(f"Unknown game type: {game_type}")

    # Create data directories
    data_dir = Path(_config.data_dir).expanduser().resolve()
    (data_dir / "saves").mkdir(parents=True, exist_ok=True)

    # Initialise the game-session manager.
    global _session_mgr
    from pokemon_agent.sessions import GameSessionManager
    _session_mgr = GameSessionManager(str(data_dir))

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


@app.get("/screenshot/grid")
async def screenshot_grid(scale: int = 4):
    """Current frame with a labelled A1..J9 movement grid drawn on top.

    The grid divides the 160x144 screen into the game's 10x9 walkable
    block layout. The player is always in cell E5 (marked). This gives a
    vision model discrete, nameable coordinates to plan movement with.
    """
    _ensure_emulator()
    try:
        from pokemon_agent.overlay import render_grid_overlay_bytes

        def _grid_png() -> bytes:
            screen = _emulator.get_screen()
            from PIL import Image
            if not isinstance(screen, Image.Image):
                import numpy as np  # noqa: F401
                screen = Image.fromarray(screen)
            return render_grid_overlay_bytes(screen, scale=scale)

        png_bytes = await _run_sync(_grid_png)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grid screenshot error: {e}")


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


@app.post("/event")
async def push_event(req: EventRequest):
    """Push an agent-narration event to the dashboard (broadcast over WS).

    The agent calls this to make its reasoning visible on the stream:
      - type "reasoning" / "decision" / "alert": send `text`
      - type "key_moment": send `description` (+ optional `category`:
        milestone | badge | catch | alert)
    These are display-only; they are NOT stored in conversation history.
    """
    event: dict = {"type": req.type}
    if req.text is not None:
        event["text"] = req.text
    if req.description is not None:
        event["description"] = req.description
    if req.category is not None:
        event["category"] = req.category
    # Persist real milestones into the active session's timeline.
    if req.type in ("key_moment", "moment") and req.description \
            and _active_session is not None and _session_mgr is not None:
        _session_mgr.add_milestone(_active_session, req.description,
                                   req.category or "milestone")
    await broadcast(event)
    return {"success": True, "broadcast_to": len(_ws_clients)}


@app.get("/objectives")
async def get_objectives():
    """Current objective list (primary/secondary/tertiary + done flags)."""
    return {"objectives": _objectives}


@app.post("/objectives")
async def set_objectives(req: ObjectivesRequest):
    """Replace the full objective list and broadcast it to the dashboard.

    The player (agent or autopilot) sets real goals here so the dashboard
    reflects the actual plan instead of static placeholder text.
    """
    global _objectives
    _objectives = [o.model_dump() for o in req.objectives]
    if _active_session is not None and _session_mgr is not None:
        _active_session.objectives = _objectives
        _session_mgr.save(_active_session)
    await broadcast({"type": "objectives", "objectives": _objectives})
    return {"success": True, "objectives": _objectives}


@app.get("/control")
async def get_control():
    """Current autopilot run state: running | paused | stopped."""
    return {"state": _control_state}


@app.post("/control")
async def set_control(req: ControlRequest):
    """Set the autopilot run state (drives the Start/Pause/Stop buttons).

    A standalone `pokemon-agent play` loop polls this and only takes actions
    while the state is "running". This endpoint is the wiring behind the
    dashboard's control buttons; it does not itself drive the emulator.
    """
    global _control_state
    valid = {"running", "paused", "stopped"}
    if req.state not in valid:
        raise HTTPException(status_code=400, detail=f"state must be one of {sorted(valid)}")
    _control_state = req.state
    await broadcast({"type": "control", "state": _control_state})
    return {"success": True, "state": _control_state}


# ---------------------------------------------------------------------------
# Game sessions — new game / load game / list / delete
# ---------------------------------------------------------------------------

def _game_summary() -> dict:
    if _active_session is None:
        return {"active": None}
    gs = _active_session
    return {"active": {"id": gs.id, "name": gs.name, "game": gs.game,
                       "hermes_session_id": gs.hermes_session_id,
                       "objectives": gs.objectives, "stats": gs.stats}}


async def _activate(gs) -> None:
    """Make `gs` the active session: sync objectives, broadcast, persist."""
    global _active_session, _objectives
    _active_session = gs
    _objectives = gs.objectives or _objectives
    _session_mgr.save(gs)
    await broadcast({"type": "objectives", "objectives": _objectives})
    await broadcast({"type": "game", **_game_summary()})


@app.get("/games")
async def list_games():
    """List all game sessions (newest first) + which one is active."""
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    return {"games": _session_mgr.list(),
            "active": _active_session.id if _active_session else None}


@app.get("/games/current")
async def current_game():
    """The active game session summary (or {active: null})."""
    return _game_summary()


@app.post("/games/new")
async def new_game(req: NewGameRequest):
    """Start a NEW game: fresh emulator boot + a fresh session manifest.

    Resets the emulator to the ROM's title/boot (no save loaded) and creates a
    new GameSession (new Hermes brain — hermes_session_id starts null and is
    bound on the autopilot's first turn).
    """
    _ensure_emulator()
    if _session_mgr is None or _config is None:
        raise HTTPException(status_code=503, detail="Server not ready")
    # Fresh boot: rebuild the emulator from the ROM (clears all game state).
    try:
        from pokemon_agent.emulator import create_emulator
        global _emulator, _reader
        # Shut down the old emulator before replacing it, otherwise the
        # previous PyBoy instance leaks on every "New Game" (its stop() is
        # never called and nothing else holds the reference).
        if _emulator is not None:
            try:
                await _run_sync(_emulator.close)
            except Exception:
                pass
        _emulator = await _run_sync(create_emulator, _config.rom_path)
        if _config.game_type == "red":
            from pokemon_agent.memory.red import PokemonRedReader
            _reader = PokemonRedReader(_emulator)
        else:
            from pokemon_agent.memory.firered import FireRedMemoryReader
            _reader = FireRedMemoryReader(_emulator)
        # tick a few frames so the title screen renders
        await _run_sync(_emulator.tick, 60)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"New-game reset failed: {e}")

    gs = _session_mgr.create(name=req.name, game=_config.game_type)
    await _activate(gs)
    await broadcast({"type": "control", "state": _control_state})
    return {"success": True, "game": gs.to_dict()}


@app.post("/games/{sid}/load")
async def load_game(sid: str):
    """Load an existing game session: restore its latest save-state and make
    it active (its Hermes session id is restored too, so the autopilot resumes
    the SAME brain). If the session has no save yet, just activate it."""
    _ensure_emulator()
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    gs = _session_mgr.load(sid)
    if gs is None:
        raise HTTPException(status_code=404, detail=f"Game session not found: {sid}")
    latest = _session_mgr.latest_save_path(sid)
    if latest is not None:
        try:
            await _run_sync(_emulator.load_state, str(latest))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load save: {e}")
    await _activate(gs)
    state_after = await _run_sync(_get_state_dict)
    await broadcast({"type": "state_update", "reason": "load_game", "state": state_after})
    return {"success": True, "game": gs.to_dict(),
            "restored_save": latest.stem if latest else None}


@app.post("/games/{sid}/hermes")
async def bind_hermes(sid: str, req: HermesSessionRequest):
    """Bind/refresh the Hermes session id for a game (autopilot calls this on
    its first turn so the run's brain memory is persisted in the manifest)."""
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    gs = (_active_session if (_active_session and _active_session.id == sid)
          else _session_mgr.load(sid))
    if gs is None:
        raise HTTPException(status_code=404, detail=f"Game session not found: {sid}")
    gs.hermes_session_id = req.hermes_session_id
    _session_mgr.save(gs)
    await broadcast({"type": "game", **_game_summary()})
    return {"success": True, "hermes_session_id": gs.hermes_session_id}


@app.delete("/games/{sid}")
async def delete_game(sid: str):
    """Delete a game session and its saves (cannot delete the active one)."""
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    if _active_session and _active_session.id == sid:
        raise HTTPException(status_code=400, detail="Cannot delete the active game; load another first.")
    ok = _session_mgr.delete(sid)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Game session not found: {sid}")
    return {"success": True, "deleted": sid}


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

        # Bump per-session stats.
        if _active_session is not None and _session_mgr is not None:
            s = _active_session.stats
            s["actions"] = s.get("actions", 0) + executed
            s["turns"] = s.get("turns", 0) + 1
            _session_mgr.save(_active_session)

        try:
            png_bytes = await _run_sync(_get_screenshot_bytes)
            screenshot_b64 = base64.b64encode(png_bytes).decode("ascii")
        except Exception:
            screenshot_b64 = None

        # Broadcast to WebSocket clients
        await broadcast({
            "type": "action",
            "actions": req.actions,
            "actions_executed": executed,
            "state_after": state_after,
        })
        # Also push the latest frame so the dashboard updates immediately
        if screenshot_b64:
            await broadcast({
                "type": "screenshot",
                "data": {"image": screenshot_b64, "format": "png"},
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
    """Save emulator state. Routed into the active game session's folder when
    one is active; otherwise the legacy flat saves/ dir."""
    _ensure_emulator()
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        if _active_session is not None and _session_mgr is not None:
            saves_dir = _session_mgr.saves_dir(_active_session.id)
        else:
            saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
            saves_dir.mkdir(parents=True, exist_ok=True)
        save_path = saves_dir / f"{req.name}.state"
        await _run_sync(_emulator.save_state, str(save_path))
        if _active_session is not None and _session_mgr is not None:
            _active_session.stats["saves"] = _active_session.stats.get("saves", 0) + 1
            _session_mgr.save(_active_session)
        return {"success": True, "path": str(save_path),
                "session": _active_session.id if _active_session else None}
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


@app.get("/map/ascii")
async def map_ascii():
    """The current on-screen walkability grid as an ASCII map (text/plain).

    @ = player (E5), . = walkable, # = blocked. Read from RAM collision data,
    so it is ground truth — not a guess from pixels.
    """
    _ensure_emulator()
    try:
        def _ascii() -> str:
            from pokemon_agent.collision import build_collision_grid, render_ascii_map
            return render_ascii_map(build_collision_grid(_reader.emu), legend=True)
        text = await _run_sync(_ascii)
        return Response(content=text, media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASCII map error: {e}")


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
        # Backfill: replay recent narration/milestone/action events so the
        # Field Log is populated immediately instead of starting empty.
        if _event_history:
            await ws.send_json({
                "type": "replay",
                "events": list(_event_history),
            })
        # Send current objectives + control state so the panel + buttons sync.
        await ws.send_json({"type": "objectives", "objectives": _objectives})
        await ws.send_json({"type": "control", "state": _control_state})
        await ws.send_json({"type": "game", **_game_summary()})
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
# Dashboard fallback — only registered if dashboard static files are missing
# ---------------------------------------------------------------------------

def _register_dashboard_fallback():
    """Register a fallback route for /dashboard if static files aren't available."""
    try:
        import pokemon_agent.dashboard as _dm
        static_dir = Path(_dm.__file__).parent / "static"
        if static_dir.is_dir() and (static_dir / "index.html").exists():
            return  # Dashboard exists — don't register fallback
    except ImportError:
        pass

    @app.get("/dashboard")
    @app.get("/dashboard/{path:path}")
    async def dashboard_fallback(path: str = ""):
        raise HTTPException(
            status_code=404,
            detail="Dashboard not installed. Install with: pip install pokemon-agent[dashboard]",
        )

_register_dashboard_fallback()
