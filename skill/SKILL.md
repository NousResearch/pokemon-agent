---
name: pokemon-player
description: Play Pokémon games via headless emulation. Start a game server, read game state, make strategic decisions, and send actions — all from the terminal.
tags: [gaming, pokemon, emulator, pyboy, gameplay]
triggers:
  - play pokemon
  - pokemon game
  - start pokemon
  - play pokemon red
  - play pokemon firered
  - pokemon firered
  - pokemon red
  - play gameboy
---

# Pokémon Player Skill

Play Pokémon games autonomously via headless emulation. Uses the `pokemon-agent`
package to run a game server, then interacts via HTTP API.

## Setup (First Time Only)

```bash
# Install the package + emulator + dashboard
pip install pokemon-agent[dashboard] pyboy

# User must provide their own ROM file
# The agent CANNOT download or distribute ROMs
```

Ask the user for the ROM file path if not provided. Common locations:
- `~/roms/pokemon_red.gb`
- `~/pokemon_red.gb`

## Starting a Game

```bash
# Start the game server as a background process
pokemon-agent serve --rom <ROM_PATH> --port 8765 &

# Verify it's running
curl -s http://localhost:8765/health
```

Tell the user: "Dashboard available at http://localhost:8765/dashboard"

## Gameplay Loop

Each turn, follow this cycle:

### 1. Observe — Read Game State

```bash
curl -s http://localhost:8765/state | python3 -m json.tool
```

Parse the JSON to understand:
- Where am I? (map name, position)
- What's happening? (overworld, battle, dialog, menu)
- Party status? (HP, levels, any fainted?)
- Bag contents? (potions, pokeballs?)
- Badges earned?

### 2. Decide — What To Do

**Priority order:**
1. If in dialog → press A to advance (`a_until_dialog_end`)
2. If in battle → choose best move (see Battle Strategy)
3. If party needs healing → navigate to Pokémon Center
4. If ready for next gym → navigate toward it
5. Otherwise → explore, train, catch Pokémon

Use Hermes memory to track:
- Current objective: `PKM:OBJECTIVE: Defeat Brock in Pewter City`
- Map knowledge: `PKM:MAP: Viridian Forest has bug catchers, exit north to Pewter`
- Strategy notes: `PKM:STRATEGY: Brock's Onix is weak to Water — use Bubble`

### 3. Act — Send Commands

```bash
# Single action
curl -s -X POST http://localhost:8765/action \
  -H "Content-Type: application/json" \
  -d '{"actions": ["press_a"]}'

# Movement sequence
curl -s -X POST http://localhost:8765/action \
  -H "Content-Type: application/json" \
  -d '{"actions": ["walk_up", "walk_up", "walk_right", "press_a"]}'

# Advance dialog
curl -s -X POST http://localhost:8765/action \
  -H "Content-Type: application/json" \
  -d '{"actions": ["a_until_dialog_end"]}'
```

### 4. Verify — Check Result

After each action, the response includes `state_after`. Check:
- Did I move? (position changed)
- Did the dialog advance? (new text or cleared)
- Did the battle state change? (HP, turn)

If stuck (same state after 3+ actions), try:
1. Press B to cancel menus
2. Try different direction
3. Load last save

## Action Reference

| Action | What It Does |
|--------|-------------|
| `press_a` | Press A (confirm, talk, interact) |
| `press_b` | Press B (cancel, run from battle) |
| `press_start` | Open menu |
| `press_select` | Select button |
| `walk_up/down/left/right` | Walk one tile |
| `wait_60` | Wait ~1 second |
| `a_until_dialog_end` | Mash A until dialog finishes |
| `hold_a_30` | Hold A for 30 frames |

## Battle Strategy (Gen 1)

### Type Effectiveness — Key Matchups
- **Water beats**: Fire, Ground, Rock
- **Fire beats**: Grass, Bug, Ice
- **Grass beats**: Water, Ground, Rock
- **Electric beats**: Water, Flying
- **Ground beats**: Fire, Electric, Rock, Poison
- **Ice beats**: Grass, Ground, Flying, Dragon
- **Fighting beats**: Normal, Rock, Ice
- **Psychic beats**: Fighting, Poison (VERY strong in Gen 1)

### Decision Tree
1. Can I one-shot? → Use strongest super-effective move
2. Am I at type disadvantage? → Switch if possible, or use neutral STAB
3. Is enemy HP high? → Consider stat moves first (Growl, Tail Whip)
4. Should I catch? → Weaken to red HP, use Poké Ball
5. Wild battle, don't need it? → Run (press_b or use "Run" option)

### Gen 1 Quirks
- Special stat is BOTH Special Attack and Special Defense
- Psychic type has NO effective counters (Ghost moves bugged, Bug moves weak)
- Critical hit rate based on Speed stat
- Wrap/Bind/Fire Spin prevent the opponent from acting

## Saving

```bash
# Save before important battles
curl -s -X POST http://localhost:8765/save \
  -d '{"name": "before_brock"}'

# Load if things go wrong
curl -s -X POST http://localhost:8765/load \
  -d '{"name": "before_brock"}'

# List available saves
curl -s http://localhost:8765/saves
```

Save before: Gym battles, catching rare Pokémon, entering dungeons.

## Progression Milestones

Track these in memory as you complete them:

1. ☐ Get starter Pokémon from Oak
2. ☐ Deliver Oak's Parcel, get Pokédex
3. ☐ Reach Pewter City through Viridian Forest
4. ☐ **Boulder Badge** (Brock — Rock type, use Water/Grass)
5. ☐ Reach Cerulean City via Mt. Moon
6. ☐ **Cascade Badge** (Misty — Water type, use Grass/Electric)
7. ☐ Board SS Anne, get HM01 Cut
8. ☐ **Thunder Badge** (Lt. Surge — Electric, use Ground)
9. ☐ Clear Rock Tunnel to Lavender Town
10. ☐ **Rainbow Badge** (Erika — Grass, use Fire/Ice/Flying)
11. ☐ Clear Team Rocket Hideout, get Silph Scope
12. ☐ **Soul Badge** (Koga — Poison, use Ground/Psychic)
13. ☐ **Marsh Badge** (Sabrina — Psychic, use Bug... but good luck in Gen 1)
14. ☐ **Volcano Badge** (Blaine — Fire, use Water/Ground)
15. ☐ **Earth Badge** (Giovanni — Ground, use Water/Grass/Ice)
16. ☐ Victory Road
17. ☐ Elite Four + Champion

## Memory Conventions

Use these prefixes in Hermes memory for Pokémon-related entries:
- `PKM:OBJECTIVE:` — Current goal
- `PKM:MAP:` — Map/navigation knowledge
- `PKM:STRATEGY:` — Battle/team strategy notes
- `PKM:PROGRESS:` — Milestone completion
- `PKM:STUCK:` — Notes about stuck situations and how they were resolved

## Taking Screenshots

```bash
# Save screenshot for vision analysis
curl -s http://localhost:8765/screenshot -o /tmp/pokemon_screen.png
```

Use `vision_analyze` on the screenshot when:
- You're unsure what's on screen (menus, NPCs)
- You need to read in-game text that RAM doesn't capture well
- You want to verify your position visually

## Stopping

When done playing:
1. Save the game: `curl -X POST localhost:8765/save -d '{"name": "session_end"}'`
2. Kill the background server process
3. Save progress notes to memory
