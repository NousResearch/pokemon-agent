"""Pokemon Gold shiny-wild-encounter farm.

Mirrors the design of ``shiny_starter.py`` but for wild Pokemon found
in grass / overworld encounter zones.  Repeatedly loads a save state
of the player standing in encounter terrain, oscillates the D-pad
along a chosen axis (mixing the RNG while accumulating step counts
that almost certainly trigger a wild encounter), then reads enemy
DVs from ``wEnemyMon`` the moment ``wBattleMode`` flips to 1.  On
non-target encounters we reload immediately — no run-from-battle
animation, no overworld walkback.

Every shiny found (target or not) is logged to ``grass_shinies.jsonl``
with the master seed, attempt index, and DV/timing data needed to
reproduce the exact roll via ``--master-seed`` + ``--replay-attempt``.

Save state requirements
-----------------------
- Player must be standing on an encounter tile (tall grass, cave
  floor, surf water, etc.).
- There must be a free encounter tile adjacent in the MOVE_AXIS
  direction so the oscillation pattern can step back and forth
  without bumping into walls/ledges (bumps don't count as steps).

Run with the project venv active:
    source .venv/bin/activate
    python shiny_grass.py

    # Show cumulative shiny history without launching the emulator:
    python shiny_grass.py --stats

    # Reproduce a previously-found shiny by its (master_seed, attempt):
    python shiny_grass.py --master-seed 0xDEADBEEFCAFEBABE --replay-attempt 4242

    # Filter to a specific species (e.g. 161 = Sentret):
    python shiny_grass.py --species 161
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import secrets
import signal
import sys
import time
from pathlib import Path

from pyboy import PyBoy

from pokemon_agent.memory.gold import (
    ADDR_BATTLE_MODE,
    ADDR_ENEMY_DVS,
    ADDR_ENEMY_LEVEL,
    ADDR_ENEMY_SPECIES,
    ADDR_JOY_LOCK,
    ADDR_TEXT_DELAY,
    SPECIES_NAMES,
)
from pokemon_agent.shiny import decode_dvs, is_shiny

ROOT = Path(__file__).resolve().parent
ROM = ROOT / "roms" / "pokemon_gold.gbc"
# User provides this — a save state of the player standing in grass /
# encounter terrain, ready to step along MOVE_AXIS.
STATE = ROOT / "roms" / "pokemon_gold.gbc.grass.state"
# On target hit, we save the post-encounter PyBoy state here so you can
# resume from inside the battle (e.g. to throw a Ball).
SHINY_STATE = ROOT / "roms" / "shiny_grass.state"
DV_LOG_PATH = ROOT / "grass_dv_log.jsonl"
SHINY_LOG_PATH = ROOT / "grass_shinies.jsonl"

# ── Run mode ────────────────────────────────────────────────────────────
SPEED = "FAST"          # FAST = unthrottled, SLOW = realtime + per-press dbg
HEADLESS = True         # True = no SDL2 window; needed for speed

# ── Target filter ───────────────────────────────────────────────────────
# Species ID to filter to.  None = accept any species (whatever the save
# state's encounter table rolls).  Gen-2 species IDs: 158=Totodile,
# 161=Sentret, 16=Pidgey, etc.  Override at runtime with --species.
TARGET_SPECIES: int | None = None

# Gen-2 shinies require DEF=SPD=SPC=10 and ATK ∈ {2,3,6,7,10,11,14,15}.
# Tighten this range to keep hunting for a better roll.
MIN_ATK_DV = 15
MAX_ATK_DV = 15

# ── Movement ────────────────────────────────────────────────────────────
# "h" = left/right oscillation, "v" = up/down.  Pick the axis along
# which your save state has a clear 2-tile-wide encounter strip.
MOVE_AXIS = "h"

# Max steps per attempt before giving up and resetting.  Gen-2 encounter
# rates run ~8-21 per 256 steps depending on terrain — mean ~12-32 steps
# per encounter.  64 gives >99% per-attempt encounter probability on the
# common terrains; bump up for sparse zones if you see "no-encounter"
# attempts in the log.
MAX_STEPS_PER_ATTEMPT = 64

# Per-step press timing.  Gen-2 needs the D-pad held ~16 frames for the
# walk animation to commit; less than that and the press just turns the
# player to face the direction without stepping (no encounter check).
WALK_HOLD_MIN = 16
WALK_HOLD_MAX = 22
WALK_GAP_MIN = 2
WALK_GAP_MAX = 6

# Probability of injecting an idle-tick jitter after each step.  Idle
# ticks shift rDIV phase and propagate cycle-level entropy into the
# wild-encounter RNG (same mechanism as in shiny_starter.py's mix_rng).
IDLE_JITTER_PROB = 0.3
IDLE_JITTER_MAX = 31

# Frames to wait after wBattleMode flips to 1 before reading wEnemyMon.
# The DVs are written before the fade animation starts, but the engine
# may still be populating other BattleMon fields the same frame, so
# give the struct a few ticks to settle.
BATTLE_SETTLE = 8

# Print a throughput line every N attempts.
THROUGHPUT_INTERVAL = 100

# Golden-ratio constant for bit-avalanche mixing of (master, attempt).
_ATTEMPT_MIX = 0x9E3779B97F4A7C15
SHOULD_EXIT = False


def attempt_rng_for(master_seed: int, attempt: int) -> random.Random:
    """Build the random.Random used to drive walk_and_mix() for *attempt*.

    Deterministic in (master_seed, attempt); independent across attempts.
    """
    return random.Random(
        master_seed ^ ((attempt * _ATTEMPT_MIX) & 0xFFFFFFFFFFFFFFFF)
    )


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_shiny_history() -> list[dict]:
    if not SHINY_LOG_PATH.exists():
        return []
    entries = []
    with open(SHINY_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def print_shiny_history(history: list[dict]) -> None:
    if not history:
        print("Shiny history: (none yet)")
        return
    targets = [s for s in history if s.get("target")]
    print(f"Shiny history: {len(history)} total, {len(targets)} matching the current filter")
    by_species: dict[str, int] = {}
    for s in history:
        name = s.get("species_name", "?")
        by_species[name] = by_species.get(name, 0) + 1
    sp_summary = ", ".join(f"{n}:{c}" for n, c in sorted(by_species.items(), key=lambda kv: -kv[1]))
    print(f"  by species: {sp_summary}")
    for s in history[-5:]:
        marker = "TARGET" if s.get("target") else "      "
        iso = s.get("iso", "?")
        print(
            f"  {marker}  {iso}  attempt={s.get('attempt'):>6}  "
            f"{s.get('species_name', '?'):>10}  L{s.get('level', '?'):>2}  "
            f"ATK={s.get('atk'):2} DEF={s.get('def'):2} "
            f"SPD={s.get('spd'):2} SPC={s.get('spc'):2}  "
            f"master={s.get('master_seed', '?')}"
        )


def _signal_handler(sig: int, _frame) -> None:
    global SHOULD_EXIT
    if SHOULD_EXIT:
        print("\nForced exit.", file=sys.stderr)
        sys.exit(1)
    print("\nSIGINT received — waiting for current attempt to finish...", file=sys.stderr)
    SHOULD_EXIT = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pokemon Gold shiny wild-encounter farm.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--master-seed",
        type=lambda s: int(s, 0),
        default=None,
        help="Override the 64-bit master seed (hex with 0x, or decimal).",
    )
    p.add_argument(
        "--replay-attempt",
        type=int,
        default=None,
        help="Run exactly one attempt at this index, save the resulting "
             "PyBoy state to roms/grass_replay_<seed>_a<N>.state, and exit.",
    )
    p.add_argument(
        "--species",
        type=int,
        default=None,
        help="Filter encounters to this species ID.  Overrides TARGET_SPECIES "
             "constant.  Pass -1 to disable species filtering for this run.",
    )
    p.add_argument(
        "--axis",
        choices=("h", "v"),
        default=None,
        help="Override MOVE_AXIS constant for this run.",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Print cumulative shiny history (from grass_shinies.jsonl) and exit.",
    )
    return p.parse_args(argv)


def log_shiny_found(
    *,
    master_seed: int,
    attempt: int,
    species: int,
    level: int,
    dvs,
    target: bool,
    target_species: int | None,
    rom_sha1: str,
    state_sha1: str,
    elapsed_s: float,
    run_frames: int,
) -> dict:
    entry = {
        "ts": time.time(),
        "iso": datetime.datetime.now().isoformat(timespec="seconds"),
        "master_seed": f"0x{master_seed:016x}",
        "attempt": attempt,
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"???({species})"),
        "level": level,
        "atk": dvs.attack,
        "def": dvs.defense,
        "spd": dvs.speed,
        "spc": dvs.special,
        "raw_dvs": f"0x{dvs.raw:04x}",
        "shiny": True,
        "target": bool(target),
        "min_atk": MIN_ATK_DV,
        "max_atk": MAX_ATK_DV,
        "target_species": target_species,
        "elapsed_s": round(elapsed_s, 2),
        "run_frames": run_frames,
        "rom_sha1": rom_sha1,
        "state_sha1": state_sha1,
        "reproduce": (
            f"python shiny_grass.py --master-seed 0x{master_seed:016x} "
            f"--replay-attempt {attempt}"
        ),
    }
    try:
        with open(SHINY_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"  warning: failed to write {SHINY_LOG_PATH}: {e}", file=sys.stderr)
    return entry


def main() -> int:
    args = parse_args()

    if args.stats:
        print_shiny_history(load_shiny_history())
        return 0
    if not STATE.exists():
        print(f"ERROR: save state not found at {STATE}", file=sys.stderr)
        print(file=sys.stderr)
        print("Create one before running this script:", file=sys.stderr)
        print("  1. python play.py", file=sys.stderr)
        print("  2. Walk into an encounter zone and stand on grass,", file=sys.stderr)
        print(f"     with a clear adjacent tile along MOVE_AXIS={MOVE_AXIS!r}.", file=sys.stderr)
        print("  3. In the PyBoy window, Shift+1 to save to slot 1.", file=sys.stderr)
        print("  4. Close the window, then:", file=sys.stderr)
        print(f"     mv roms/pokemon_gold.gbc.state1 {STATE}", file=sys.stderr)
        return 1

    if SPEED not in ("FAST", "SLOW"):
        print(f"ERROR: SPEED must be 'FAST' or 'SLOW', got {SPEED!r}", file=sys.stderr)
        return 1
    slow = SPEED == "SLOW"

    # Resolve runtime overrides.
    move_axis = args.axis if args.axis is not None else MOVE_AXIS
    if args.species is None:
        target_species: int | None = TARGET_SPECIES
    elif args.species == -1:
        target_species = None
    else:
        target_species = args.species

    master_seed = (
        args.master_seed if args.master_seed is not None else secrets.randbits(64)
    )
    replay_attempt = args.replay_attempt

    rom_sha1 = file_sha1(ROM)
    state_sha1 = file_sha1(STATE)

    history = load_shiny_history()
    print_shiny_history(history)
    print()
    print(f"MASTER_SEED=0x{master_seed:016x}")
    print(f"ROM sha1={rom_sha1[:12]}…  save_state sha1={state_sha1[:12]}…")
    if replay_attempt is not None:
        print(
            f"REPLAY MODE: running only attempt {replay_attempt} "
            f"with master_seed=0x{master_seed:016x}, then exiting."
        )
    species_name = (
        "any" if target_species is None
        else f"{SPECIES_NAMES.get(target_species, '?')} (id={target_species})"
    )
    print(
        f"Hunting shiny wild encounter — species={species_name}  "
        f"ATK DV in [{MIN_ATK_DV}, {MAX_ATK_DV}]  axis={move_axis!r}  "
        f"(HEADLESS={HEADLESS}, SPEED={SPEED})"
    )

    pyboy = PyBoy(str(ROM), window="null" if HEADLESS else "SDL2")
    try:
        pyboy.sound_emulated = False
    except AttributeError:
        pass
    pyboy.set_emulation_speed(0 if not slow else 1)

    frame_count = [0]
    total_frames = [0]
    start_time = time.monotonic()

    count_encounters = 0
    count_no_encounter = 0
    count_shiny = 0
    count_target = 0
    species_seen: dict[int, int] = {}

    dv_log = open(DV_LOG_PATH, "a", buffering=1)

    # -- low-level helpers --------------------------------------------------

    def tick(n: int = 1) -> None:
        for _ in range(n):
            if SHOULD_EXIT:
                raise KeyboardInterrupt()
            if not pyboy.tick(render=False):
                sys.exit(0)
            frame_count[0] += 1
            total_frames[0] += 1

    def press(button: str, hold: int, gap: int) -> None:
        pyboy.button_press(button)
        tick(hold)
        pyboy.button_release(button)
        tick(gap)

    def read_u8(addr: int) -> int:
        return pyboy.memory[addr] & 0xFF

    def dbg(msg: str) -> None:
        if slow:
            print(f"[f={frame_count[0]:>6}] {msg}", flush=True)

    def load_state() -> None:
        with open(STATE, "rb") as f:
            pyboy.load_state(f)
        tick(4)

    def in_battle() -> bool:
        return read_u8(ADDR_BATTLE_MODE) != 0

    def read_enemy():
        species = read_u8(ADDR_ENEMY_SPECIES)
        b0 = read_u8(ADDR_ENEMY_DVS)
        b1 = read_u8(ADDR_ENEMY_DVS + 1)
        level = read_u8(ADDR_ENEMY_LEVEL)
        return species, level, decode_dvs(b0, b1)

    # -- the combined walk-and-mix step ------------------------------------

    def walk_and_mix(attempt: int, rng: random.Random) -> bool:
        """Oscillate along MOVE_AXIS until an encounter triggers or we
        exhaust MAX_STEPS_PER_ATTEMPT.

        Each step uses randomized hold/gap and an optional idle-tick
        jitter, both of which mix the Gen-2 RNG (input handler + VBlank
        rDIV reads).  Returns True if wBattleMode flipped to nonzero.
        """
        btn_pair = ("left", "right") if move_axis == "h" else ("up", "down")
        for step in range(MAX_STEPS_PER_ATTEMPT):
            if in_battle():
                return True
            button = btn_pair[step & 1]
            hold = rng.randint(WALK_HOLD_MIN, WALK_HOLD_MAX)
            gap = rng.randint(WALK_GAP_MIN, WALK_GAP_MAX)
            press(button, hold=hold, gap=gap)
            if rng.random() < IDLE_JITTER_PROB:
                tick(rng.randint(0, IDLE_JITTER_MAX))
            if in_battle():
                return True
        dbg(f"walk_and_mix attempt={attempt} no encounter after {MAX_STEPS_PER_ATTEMPT} steps")
        return False

    # -- main loop ---------------------------------------------------------

    attempt = (replay_attempt - 1) if replay_attempt is not None else 0
    signal.signal(signal.SIGINT, _signal_handler)
    try:
        while True:
            if SHOULD_EXIT:
                break
            attempt += 1
            frame_count[0] = 0
            load_state()
            dbg(
                f"=== attempt {attempt} (SPEED={SPEED}, HEADLESS={HEADLESS}, "
                f"master=0x{master_seed:016x}, axis={move_axis!r}) ==="
            )

            rng = attempt_rng_for(master_seed, attempt)
            triggered = walk_and_mix(attempt, rng)

            if not triggered:
                count_no_encounter += 1
                print(
                    f"[{attempt:>4}] no encounter after {MAX_STEPS_PER_ATTEMPT} steps",
                    file=sys.stderr,
                )
                continue

            # Let wEnemyMon settle: DVs land before the fade animation,
            # but other BattleMon fields populate over a few frames.
            tick(BATTLE_SETTLE)
            species, level, dvs = read_enemy()
            shiny = is_shiny(dvs)
            atk_ok = MIN_ATK_DV <= dvs.attack <= MAX_ATK_DV
            species_ok = (target_species is None) or (species == target_species)
            target = shiny and atk_ok and species_ok
            species_name = SPECIES_NAMES.get(species, f"???({species})")

            count_encounters += 1
            species_seen[species] = species_seen.get(species, 0) + 1

            if target:
                status = "*** TARGET SHINY ***"
            elif shiny:
                reasons = []
                if not atk_ok:
                    reasons.append(f"ATK {dvs.attack} outside [{MIN_ATK_DV},{MAX_ATK_DV}]")
                if not species_ok:
                    reasons.append(f"species {species_name} ≠ filter")
                status = f"*** SHINY ({'; '.join(reasons)}) ***"
            else:
                status = "not shiny"
            print(
                f"[{attempt:>4}] {species_name:>10} L{level:>2}  "
                f"ATK={dvs.attack:2d} DEF={dvs.defense:2d} "
                f"SPD={dvs.speed:2d} SPC={dvs.special:2d}  "
                f"{status}"
            )

            if shiny:
                count_shiny += 1
            if target:
                count_target += 1

            # One line-buffered JSONL write — survives a kill -9.
            dv_log.write(
                f'{{"a":{attempt},"sp":{species},"lvl":{level},'
                f'"atk":{dvs.attack},"def":{dvs.defense},'
                f'"spd":{dvs.speed},"spc":{dvs.special},'
                f'"shiny":{int(shiny)},"target":{int(target)},'
                f'"master":"0x{master_seed:016x}"}}\n'
            )

            if attempt % THROUGHPUT_INTERVAL == 0:
                elapsed = time.monotonic() - start_time
                rate = attempt / elapsed if elapsed > 0 else 0.0
                avg_frames = total_frames[0] / attempt
                enc_rate = count_encounters / attempt if attempt else 0.0
                top_sp = sorted(species_seen.items(), key=lambda kv: -kv[1])[:5]
                sp_summary = ", ".join(
                    f"{SPECIES_NAMES.get(sp, '?')}:{c}" for sp, c in top_sp
                )
                print(
                    f"[{attempt}] rate: {rate:.2f} a/s, {avg_frames:.0f} f/a, "
                    f"encounter rate: {enc_rate:.1%}"
                )
                print(
                    f"  shinies: {count_shiny} (exp {count_encounters/8192:.2f}), "
                    f"targets: {count_target}, "
                    f"no-encounter attempts: {count_no_encounter}"
                )
                print(f"  top species: {sp_summary}")

            if shiny:
                shiny_elapsed = time.monotonic() - start_time
                log_shiny_found(
                    master_seed=master_seed,
                    attempt=attempt,
                    species=species,
                    level=level,
                    dvs=dvs,
                    target=target,
                    target_species=target_species,
                    rom_sha1=rom_sha1,
                    state_sha1=state_sha1,
                    elapsed_s=shiny_elapsed,
                    run_frames=total_frames[0],
                )
                tag = "TARGET" if target else "non-target"
                print(
                    f"  → logged {tag} shiny to {SHINY_LOG_PATH.name}.  "
                    f"Reproduce with: --master-seed 0x{master_seed:016x} "
                    f"--replay-attempt {attempt}"
                )

            if replay_attempt is not None:
                replay_state_path = ROOT / "roms" / (
                    f"grass_replay_{master_seed:016x}_a{attempt}.state"
                )
                with open(replay_state_path, "wb") as f:
                    pyboy.save_state(f)
                print(
                    f"REPLAY DONE: attempt={attempt} "
                    f"{species_name} L{level} "
                    f"ATK={dvs.attack} DEF={dvs.defense} "
                    f"SPD={dvs.speed} SPC={dvs.special} "
                    f"{'shiny' if shiny else 'not shiny'}"
                    f"{' (target)' if target else ''}"
                )
                print(f"REPLAY DONE: state saved to {replay_state_path}")
                break

            if not target:
                continue

            # ── Target found — snapshot in-battle state and exit. ──
            elapsed = time.monotonic() - start_time
            avg_rate = attempt / elapsed if elapsed > 0 else 0.0

            print()
            print("=" * 60)
            print(f"  ✨  SHINY {species_name}  ✨   on attempt {attempt}")
            print(
                f"  Level {level}  "
                f"ATK={dvs.attack}  DEF={dvs.defense}  "
                f"SPD={dvs.speed}  SPC={dvs.special}"
            )
            print(f"  Total attempts: {attempt}  ({count_encounters} encounters)")
            print(f"  Total elapsed:  {elapsed:.1f}s")
            print(f"  Avg rate:       {avg_rate:.2f} attempts/sec")
            print("=" * 60)
            print()

            with open(SHINY_STATE, "wb") as f:
                pyboy.save_state(f)
            print(f"Saved in-battle state to {SHINY_STATE}")
            print("Load it in play.py and throw a Pokeball before fleeing!")
            if not HEADLESS:
                print("Window stays open.  Close it (or Ctrl+C) to exit.")
                while pyboy.tick():
                    if SHOULD_EXIT:
                        break
            return 0

    except KeyboardInterrupt:
        print(file=sys.stderr)
    finally:
        try:
            dv_log.close()
        except Exception:
            pass
        pyboy.stop(save=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
