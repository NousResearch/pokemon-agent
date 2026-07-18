# 🎮 pokemon-agent

**AI-powered Pokémon gameplay agent with headless emulation, REST API, and live dashboard.**

Let any AI agent — [Hermes Agent](https://github.com/NousResearch/hermes-agent), Claude Code, Codex, or your own — play Pokémon games autonomously via a clean HTTP API. Runs headlessly on any server or terminal. No display, no GUI, no emulator window needed.

```
┌──────────────────────┐
│   Your AI Agent      │  Any LLM-powered agent
│   (Hermes, Claude,   │  makes the decisions
│    Codex, custom)    │
└─────────┬────────────┘
          │ HTTP API
┌─────────▼────────────┐
│   pokemon-agent      │  This package:
│   ┌────────────────┐ │  - Headless emulator
│   │ Game Server    │ │  - Memory reader
│   │ (FastAPI)      │ │  - Game state parser
│   ├────────────────┤ │  - REST + WebSocket API
│   │ Emulator       │ │  - Optional dashboard
│   │ (PyBoy/PyGBA)  │ │
│   └────────────────┘ │
└──────────────────────┘
```

## Features

- **🔌 Headless emulation** — No display server, X11, or GUI needed. Pure in-process emulation.
- **🌐 REST API** — `GET /state`, `POST /action`, `GET /screenshot` — control the game over HTTP.
- **🗺️ Ground-truth navigation** — RAM-derived collision map (`GET /map/ascii`) and a labelled A1..J9 grid overlay (`GET /screenshot/grid`) so an agent navigates from real walkability data instead of guessing from pixels.
- **📡 WebSocket** — Real-time event streaming for live monitoring.
- **🧠 Structured game state** — RAM is parsed into clean JSON: party, bag, badges, map, battle, dialog, collision grid.
- **🎨 Live "Field Log" dashboard** — Editorial broadcast UI: the agent's reasoning stream, live grid map, objectives, telemetry (stuck-meter, blackout counter), and a milestone timeline.
- **🎮 Multi-game** — Supports Game Boy (Pokémon Red/Blue) via PyBoy, GBA (FireRed) via PyGBA.
- **🤖 Agent-agnostic** — Works with any AI agent, RL framework, or custom script.

## Quick Start

### Installation

```bash
# Clone the repository, then run these commands from the project directory.

# Core installation with the PyBoy emulator
python -m pip install --upgrade pip
python -m pip install ".[pyboy]"

# With the optional web dashboard
python -m pip install ".[pyboy,dashboard]"
```

#### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install ".[pyboy,dashboard]"

pip check
pokemon-agent --help
```

> **Note:** You must provide your own ROM file. This package does not include any game ROMs.

### Start the Server

```bash
pokemon-agent serve --rom path/to/pokemon_red.gb
```

```
╔══════════════════════════════════════╗
║       🎮 Pokémon Agent Server       ║
╚══════════════════════════════════════╝
  Game:       Pokemon Red
  ROM:        pokemon_red.gb
  API:        http://localhost:8765
  Dashboard:  http://localhost:8765/dashboard
  WebSocket:  ws://localhost:8765/ws
```

### Game sessions — new game / load game

A *game session* is one named playthrough that binds three things together:
the **Hermes brain** (its session id, so memory carries across turns), the
**emulator save-states** (game progress), and **objectives + milestones +
stats** — all persisted under `<data_dir>/games/<id>/`.

From the dashboard GAME panel: **+ NEW** starts a fresh game (resets the
emulator to a clean boot + new manifest + new Hermes brain), **LOAD** lists
past sessions and restores one — its latest save-state *and* the same Hermes
session it was played with. Or via the API:

```bash
curl -X POST localhost:8765/games/new -d '{"name":"Nuzlocke run"}'   # new game
curl localhost:8765/games                                            # list sessions
curl -X POST localhost:8765/games/<id>/load                          # load one
curl localhost:8765/games/current                                    # active session
```

Saves, objectives, milestones, and stats are automatically scoped to the
active session, and the autopilot binds to it — so loading a game resumes
exactly where that run (and its Hermes memory) left off.

### Autopilot — Hermes Agent plays itself

The server is a passive API — it holds the emulator but does not play. To make
the game play autonomously, run the bundled driver in a second process:

```bash
# 1. start the server (terminal A)
pokemon-agent serve --rom path/to/pokemon_red.gb

# 2. start the driver (terminal B) — requires the `hermes` CLI on PATH
pokemon-agent play --port 8765
```

The brain is a real **Hermes Agent** session, not a bare LLM. Each turn the
driver invokes `hermes chat --resume <session> --yolo -s pokemon-player
--image <grid screenshot> -q "<state + map>"`, so Hermes plays with its full
stack — the `pokemon-player` skill, vision, memory, and the terminal tool —
and keeps context across the whole run via one persistent session. Hermes
itself curls the server to POST `/action`, `/event` (narration), and
`/objectives`.

The driver idles until you press **START** on the dashboard (it polls
`/control`); **START / PAUSE / STOP** drive it live. Hermes uses its own
configured provider/model; override per-run with `POKEMON_HERMES_MODEL` /
`POKEMON_HERMES_PROVIDER`. Each turn is a full agent loop (seconds-to-minutes),
not a single API call — this is genuine agentic play, not a tight poll.

### Play from Any Agent

```bash
# Get game state
curl http://localhost:8765/state | python -m json.tool

# Take a screenshot
curl http://localhost:8765/screenshot -o screen.png

# Send actions
curl -X POST http://localhost:8765/action \
  -H "Content-Type: application/json" \
  -d '{"actions": ["walk_up", "walk_up", "press_a"]}'

# Save/load state
curl -X POST http://localhost:8765/save -d '{"name": "before_brock"}'
curl -X POST http://localhost:8765/load -d '{"name": "before_brock"}'
```

### Game State (JSON)

```json
{
  "player": {
    "name": "ASH",
    "money": 3000,
    "badges": 1,
    "badges_list": ["Boulder"],
    "position": {"map_id": 1, "map_name": "PALLET TOWN", "x": 7, "y": 5},
    "facing": "down",
    "play_time": {"hours": 1, "minutes": 23, "seconds": 45}
  },
  "party": [
    {
      "nickname": "SQUIRTLE",
      "species": "Squirtle",
      "level": 12,
      "hp": 33,
      "max_hp": 33,
      "moves": ["Tackle", "Tail Whip", "Bubble"],
      "status": null,
      "types": ["Water"]
    }
  ],
  "bag": [{"item": "Potion", "quantity": 3}],
  "battle": null,
  "dialog": {"active": false, "text": null},
  "flags": {"has_pokedex": true, "badges_earned": ["Boulder"]},
  "metadata": {"game": "Pokemon Red", "frame_count": 12345}
}
```

## Actions Reference

| Action | Description |
|--------|-------------|
| `press_a` | Press A button (10 frames press + 20 wait) |
| `press_b` | Press B button |
| `press_start` | Press Start button |
| `press_select` | Press Select button |
| `walk_up` | Walk one tile up (16 frames + 8 wait) |
| `walk_down` | Walk one tile down |
| `walk_left` | Walk one tile left |
| `walk_right` | Walk one tile right |
| `hold_a_30` | Hold A for 30 frames |
| `wait_60` | Wait 60 frames (~1 second) |
| `a_until_dialog_end` | Press A repeatedly until dialog closes |

## Dashboard

Install with the dashboard extra to get a live web GUI:

```bash
pip install pokemon-agent[dashboard]
```

Then open `http://localhost:8765/dashboard` in your browser.

The dashboard ("Field Log") is an editorial broadcast UI — designed to be
watched, not just a debug console. It shows:
- **Reasoning stream** — the agent's THINK / DECIDE / ACT / MILESTONE / ALERT
  narration, typeset as distinct entries (push it via `POST /event`)
- **Game stage** — live screenshot with a SCREEN ⇄ GRID MAP toggle (grid map
  shows the labelled, walkability-tinted overlay)
- **Instruments** — gym badges, three-tier objectives, telemetry (a live
  stuck-meter, blackout / caught / action counters), and a milestone timeline
- **Party belt** — all six slots with types, HP bars, status, and moves

## Supported Games

| Game | Emulator | Status | Install |
|------|----------|--------|---------|
| Pokémon Red/Blue | PyBoy | ✅ Supported | `pip install pyboy` |
| Pokémon Yellow | PyBoy | ✅ Supported | `pip install pyboy` |
| Pokémon Gold/Silver | PyBoy | 🔜 Planned | `pip install pyboy` |
| Pokémon FireRed/LeafGreen | PyGBA | 🔜 Phase 2 | `pip install pygba` |
| Pokémon Ruby/Sapphire/Emerald | PyGBA | 🔜 Phase 2 | `pip install pygba` |

## Use with Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) has a built-in `pokemon-player` skill:

```
You: "Play Pokémon Red"
Hermes: *installs pokemon-agent, starts server, begins playing*
```

The skill teaches Hermes battle strategy, exploration patterns, team management, and how to use its persistent memory for tracking objectives across sessions.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Server info |
| `/state` | GET | Full game state JSON (includes `collision` walkability grid for Red) |
| `/screenshot` | GET | Current frame (PNG) |
| `/screenshot/grid` | GET | Current frame with a labelled A1..J9 grid + walkability tint (PNG) |
| `/screenshot/base64` | GET | Current frame (base64 JSON) |
| `/map/ascii` | GET | Ground-truth ASCII walkability map (`@`/`.`/`#`) |
| `/action` | POST | Execute game actions |
| `/event` | POST | Push agent narration (reasoning/decision/key_moment/alert) to the dashboard |
| `/objectives` | GET/POST | Read or replace the dashboard objective list (dynamic goals) |
| `/control` | GET/POST | Read or set the autopilot run state (running/paused/stopped) |
| `/games` | GET | List all game sessions + which is active |
| `/games/new` | POST | Start a new game (fresh boot + new session) |
| `/games/{id}/load` | POST | Load a game session (restore save + Hermes brain) |
| `/games/{id}/hermes` | POST | Bind the Hermes session id to a game |
| `/games/{id}` | DELETE | Delete a game session and its saves |
| `/games/current` | GET | The active game session summary |
| `/save` | POST | Save emulator state |
| `/load` | POST | Load emulator state |
| `/saves` | GET | List saved states |
| `/minimap` | GET | ASCII minimap |
| `/health` | GET | Health check |
| `/ws` | WebSocket | Live event stream |
| `/dashboard` | GET | Web dashboard (if installed) |

## Python API

You can also use `pokemon-agent` as a library:

```python
from pokemon_agent.emulator import create_emulator
from pokemon_agent.memory.red import PokemonRedReader
from pokemon_agent.state.builder import build_game_state

# Load ROM headlessly
emu = create_emulator("pokemon_red.gb")

# Create memory reader
reader = PokemonRedReader(emu)

# Get structured game state
state = build_game_state(reader)
print(f"Player: {state['player']['name']}")
print(f"Badges: {state['player']['badges']}")
print(f"Party: {[p['species'] for p in state['party']]}")

# Send inputs
emu.press("a", frames=10)
emu.tick(20)

# Get screenshot
image = emu.get_screen()  # PIL Image
image.save("screenshot.png")
```

## Architecture

```
pokemon_agent/
├── __init__.py          # Package version
├── cli.py               # CLI entry point (pokemon-agent command)
├── server.py            # FastAPI game server (REST + WebSocket)
├── emulator.py          # PyBoy/PyGBA wrapper (headless)
├── collision.py         # RAM walkability map (per-tileset collision -> 10x9 grid)
├── overlay.py           # Labelled A1..J9 grid + walkability-tint screenshot overlay
├── pathfinding.py       # A* grid navigation
├── memory/
│   ├── reader.py        # Abstract game memory reader
│   ├── red.py           # Pokémon Red/Blue RAM parser
│   └── firered.py       # FireRed RAM parser (Phase 2)
├── state/
│   └── builder.py       # Structured state builder
└── dashboard/           # Optional [dashboard] extra
    ├── mount.py         # FastAPI static mount
    ├── history.py       # JSONL event logger
    └── static/
        ├── index.html   # Dashboard page
        ├── style.css    # Dark cyberpunk theme
        └── app.js       # WebSocket client
```

## Contributing

Contributions welcome! Areas where help is needed:

- **Pokémon Gold/Silver/Crystal** memory reader (`memory/gold.py`)
- **Pokémon FireRed** full memory reader with decryption (`memory/firered.py`)
- **Pokémon Emerald** memory reader (`memory/emerald.py`)
- **Battle AI** improvements and type matchup optimization
- **Dashboard** enhancements (progress tracking, key moments, replay)
- **Tests** for memory readers and state builders

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [PyBoy](https://github.com/Baekalfen/PyBoy) — Game Boy emulator in Python
- [PyGBA](https://github.com/dvruette/pygba) — GBA emulator wrapper
- [pret/pokered](https://github.com/pret/pokered) — Pokémon Red decompilation (memory addresses)
- [pret/pokefirered](https://github.com/pret/pokefirered) — FireRed decompilation
- [gpt-play-pokemon-firered](https://github.com/Clad3815/gpt-play-pokemon-firered) — Architecture inspiration
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — AI agent platform by Nous Research
