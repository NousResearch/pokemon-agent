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
- **📡 WebSocket** — Real-time event streaming for live monitoring.
- **🧠 Structured game state** — RAM is parsed into clean JSON: party, bag, badges, map, battle, dialog.
- **🎨 Live dashboard** — Optional web GUI to watch the AI play (Claude Plays Pokémon style).
- **🎮 Multi-game** — Supports Game Boy (Pokémon Red/Blue) via PyBoy, GBA (FireRed) via PyGBA.
- **🤖 Agent-agnostic** — Works with any AI agent, RL framework, or custom script.

## Quick Start

### Installation

```bash
# Core (emulator + API server)
pip install pokemon-agent pyboy

# With dashboard (optional web GUI)
pip install pokemon-agent[dashboard] pyboy
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

The dashboard shows:
- **Live game screenshot** — Updated each turn with decorative corner brackets
- **AI reasoning stream** — Watch the agent think in real-time
- **Team status** — All party Pokémon with HP bars, types, levels
- **Badge progress** — Visual badge tracker
- **Action log** — Color-coded history of all actions and reasoning

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
| `/state` | GET | Full game state JSON |
| `/screenshot` | GET | Current frame (PNG) |
| `/screenshot/base64` | GET | Current frame (base64 JSON) |
| `/action` | POST | Execute game actions |
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
