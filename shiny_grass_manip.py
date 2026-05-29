"""Deterministic-RNG-write shiny WILD-ENCOUNTER farm.

The wild-encounter analogue of ``shiny_starter_manip.py``.  Same core
trick: capture a save state *just before* the enemy DV-gen ``Random()``
calls, then write ``hRandomSub`` (0xFFE4) to deterministically control
the high byte of the enemy DVs.  Sweep tick offsets to vary the rDIV
phase at DV-gen time, which changes the fixed delta
``(DV1 - DV0) mod 256`` until it lines up with a shiny target.

How wild encounters differ from the starter
--------------------------------------------
The starter rolls DVs on a deterministic A-press (the "received
POKEMON!" textbox close), so we always know exactly which press fires
the DV-gen calls.  A wild encounter instead rolls DVs when
``wBattleMode`` flips to 1 — but that flip is *gated by a step-based
encounter check*.  We can't press a single button to force it; we have
to walk until the encounter check fires.

So calibration is **empirical**.  We:

  1. Walk along ``MOVE_AXIS`` with fixed timing, snapshotting every
     frame into a rolling window, until ``wBattleMode`` flips.
  2. Backward-scan that window for the *latest* frame where writing
     ``hRandomSub`` still changes the enemy DV byte-0 **and** leaves the
     species unchanged.  That frame is past the encounter/species roll
     but before the DV roll — exactly our PRE_DV state.

Because the whole walk is deterministic for a fixed (grass.state, T),
re-running with a different ``hRandomSub`` still triggers the same
encounter (the encounter + species were already decided by the time we
reach PRE_DV); only the DVs change.

The rDIV-phase knob is ``T`` — extra idle ticks injected *before* the
walk.  Each T shifts the whole RNG timeline, generally changing both
the delta and (often) which species is rolled.

Save state requirement
----------------------
``roms/pokemon_gold.gbc.grass.state`` — player standing on an encounter
tile with a clear adjacent tile along ``MOVE_AXIS`` so the oscillation
can step back and forth without bumping walls.  (Same requirement as
``shiny_grass.py``.)

Run with the project venv active:
    source .venv/bin/activate
    python shiny_grass_manip.py --find-target            # search for a target shiny
    python shiny_grass_manip.py --find-target --species 161   # filter species
    python shiny_grass_manip.py --build-state            # build+inspect PRE_DV at T=0
    python shiny_grass_manip.py --probe 0x00 0x57        # one-shot probe at T=0
    python shiny_grass_manip.py --stats                  # show manip shiny history
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import io
import json
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
    SPECIES_NAMES,
)
from pokemon_agent.shiny import decode_dvs, is_shiny

ROOT = Path(__file__).resolve().parent
ROM = ROOT / "roms" / "pokemon_gold.gbc"
# Player standing in encounter terrain, ready to step along MOVE_AXIS.
GRASS_STATE = ROOT / "roms" / "pokemon_gold.gbc.grass.state"
# Built PRE_DV calibration state (1 frame before enemy DV gen) at T=0.
PRE_DV_STATE = ROOT / "roms" / "pokemon_gold.gbc.grass.pre_dv.state"
# On a target hit, the in-battle state (enemy is the shiny) is saved here.
SHINY_STATE = ROOT / "roms" / "shiny_grass_manip.state"
DV_LOG_PATH = ROOT / "grass_manip_dv_log.jsonl"
SHINY_LOG_PATH = ROOT / "grass_manip_shinies.jsonl"

SPEED = "FAST"
HEADLESS = True

# ── Target filter ───────────────────────────────────────────────────────
# None = accept whatever species the encounter table rolls.
TARGET_SPECIES: int | None = None
MIN_ATK_DV = 15
MAX_ATK_DV = 15

# ── Movement ────────────────────────────────────────────────────────────
MOVE_AXIS = "h"     # "h" = left/right oscillation, "v" = up/down.

# Fixed per-step timing.  Unlike shiny_grass.py these are constants (no
# RNG) so the walk is fully deterministic for a fixed (grass.state, T) —
# determinism is what makes the manip reproducible.
MANIP_WALK_HOLD = 16
MANIP_WALK_GAP = 4
MAX_STEPS_PER_WALK = 80

# Rolling window of per-frame snapshots kept while approaching the
# encounter.  Must comfortably exceed the gap between the DV-gen frame
# and the wBattleMode flip (a handful of frames in practice).
SNAPSHOT_WINDOW = 48

# Frames to wait after wBattleMode flips before reading wEnemyMon, so the
# BattleMon struct finishes populating.
BATTLE_SETTLE = 8
# Frame budget for ticking a PRE_DV/probe state forward into battle.
BATTLE_TICK_BUDGET = SNAPSHOT_WINDOW + BATTLE_SETTLE + 16

# Gen-2 RNG state in HRAM (Gold/Silver; verified vs pret/pokegold).
ADDR_H_RANDOM_ADD = 0xFFE3
ADDR_H_RANDOM_SUB = 0xFFE4
ADDR_DIV = 0xFF04

# Probe pair used by the backward scan to detect DV control.
SCAN_SUB_A = 0xAA
SCAN_SUB_B = 0x55

SHINY_ATKS = (2, 3, 6, 7, 10, 11, 14, 15)
SHOULD_EXIT = False


# ────────────────────────────────────────────────────────────────────────
# misc helpers
# ────────────────────────────────────────────────────────────────────────

def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def target_b0s_for_filter(min_atk: int, max_atk: int) -> list[int]:
    """DV byte-0 values satisfying (shiny + ATK in [min, max])."""
    return [atk * 16 + 10 for atk in SHINY_ATKS if min_atk <= atk <= max_atk]


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
        print("Grass-manip shiny history: (none yet)")
        return
    targets = [s for s in history if s.get("target")]
    print(f"Grass-manip shiny history: {len(history)} total, "
          f"{len(targets)} matching a target filter")
    for s in history[-10:]:
        marker = "TARGET" if s.get("target") else "      "
        print(
            f"  {marker}  {s.get('iso', '?')}  T={s.get('offset'):>3}  "
            f"sub=0x{s.get('rng_sub', 0):02X}  "
            f"{s.get('species_name', '?'):>10} L{s.get('level', '?'):>2}  "
            f"ATK={s.get('atk'):2} DEF={s.get('def'):2} "
            f"SPD={s.get('spd'):2} SPC={s.get('spc'):2}"
        )


def log_shiny_found(*, offset: int, rng_sub: int, species: int, level: int,
                    dvs, target: bool, target_species: int | None,
                    rom_sha1: str, elapsed_s: float) -> None:
    entry = {
        "ts": time.time(),
        "iso": datetime.datetime.now().isoformat(timespec="seconds"),
        "offset": offset,
        "rng_add": 0,
        "rng_sub": rng_sub,
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"???({species})"),
        "level": level,
        "atk": dvs.attack, "def": dvs.defense,
        "spd": dvs.speed, "spc": dvs.special,
        "raw_dvs": f"0x{dvs.raw:04x}",
        "shiny": True, "target": bool(target),
        "min_atk": MIN_ATK_DV, "max_atk": MAX_ATK_DV,
        "target_species": target_species,
        "axis": MOVE_AXIS,
        "elapsed_s": round(elapsed_s, 2),
        "rom_sha1": rom_sha1,
        "reproduce": (f"python shiny_grass_manip.py --replay-offset {offset} "
                      f"--sub 0x{rng_sub:02X}"),
    }
    try:
        with open(SHINY_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"  warning: failed to write {SHINY_LOG_PATH}: {e}", file=sys.stderr)


def _signal_handler(sig: int, _frame) -> None:
    global SHOULD_EXIT
    if SHOULD_EXIT:
        print("\nForced exit.", file=sys.stderr)
        sys.exit(1)
    print("\nSIGINT — finishing current offset then exiting...", file=sys.stderr)
    SHOULD_EXIT = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pokemon Gold deterministic-RNG-write wild-encounter farm.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--find-target", action="store_true",
                   help="Multi-offset deterministic search for any shiny in the "
                        "current ATK/species filter.  Stops at first hit.")
    p.add_argument("--max-offsets", type=int, default=256,
                   help="Upper bound on idle-tick offsets T to try.")
    p.add_argument("--build-state", action="store_true",
                   help="Build PRE_DV at T=0, save to disk, print its delta/species, exit.")
    p.add_argument("--probe", nargs=2, type=lambda s: int(s, 0), default=None,
                   metavar=("ADD", "SUB"),
                   help="One-shot probe at T=0: build PRE_DV, write (add, sub), "
                        "tick to battle, print enemy species+DVs.")
    p.add_argument("--replay-offset", type=int, default=None,
                   help="Rebuild PRE_DV at this offset T and probe with --sub.")
    p.add_argument("--sub", type=lambda s: int(s, 0), default=0,
                   help="hRandomSub value for --replay-offset.")
    p.add_argument("--species", type=int, default=None,
                   help="Filter encounters to this species ID (-1 disables).")
    p.add_argument("--axis", choices=("h", "v"), default=None,
                   help="Override MOVE_AXIS for this run.")
    p.add_argument("--stats", action="store_true",
                   help="Print cumulative grass-manip shiny history and exit.")
    return p.parse_args(argv)


# ────────────────────────────────────────────────────────────────────────
# helpers closing over pyboy
# ────────────────────────────────────────────────────────────────────────

def make_helpers(pyboy: PyBoy, total_frames: list[int], axis: str):
    btn_pair = ("left", "right") if axis == "h" else ("up", "down")

    def tick(n: int = 1) -> None:
        for _ in range(n):
            if SHOULD_EXIT:
                raise KeyboardInterrupt()
            if not pyboy.tick(render=False):
                sys.exit(0)
            total_frames[0] += 1

    def read_u8(addr: int) -> int:
        return pyboy.memory[addr] & 0xFF

    def in_battle() -> bool:
        return read_u8(ADDR_BATTLE_MODE) != 0

    def state_to_bytes() -> bytes:
        buf = io.BytesIO()
        pyboy.save_state(buf)
        return buf.getvalue()

    def state_from_bytes(b: bytes) -> None:
        pyboy.load_state(io.BytesIO(b))

    def read_enemy() -> tuple[int, int, object]:
        species = read_u8(ADDR_ENEMY_SPECIES)
        b0 = read_u8(ADDR_ENEMY_DVS)
        b1 = read_u8(ADDR_ENEMY_DVS + 1)
        level = read_u8(ADDR_ENEMY_LEVEL)
        return species, level, decode_dvs(b0, b1)

    return {
        "btn_pair": btn_pair,
        "tick": tick,
        "read_u8": read_u8,
        "in_battle": in_battle,
        "state_to_bytes": state_to_bytes,
        "state_from_bytes": state_from_bytes,
        "read_enemy": read_enemy,
    }


# ────────────────────────────────────────────────────────────────────────
# Calibration — find the PRE_DV state at a given offset T
# ────────────────────────────────────────────────────────────────────────

def walk_capturing_window(pyboy: PyBoy, h, T: int) -> collections.deque | None:
    """From grass.state, idle T frames, then walk along the axis with
    fixed timing, snapshotting every frame into a rolling window, until
    wBattleMode flips.

    Returns the deque of (frame_idx, snapshot_bytes) leading up to the
    battle flip, or None if no encounter triggered within budget.
    """
    tick = h["tick"]
    in_battle = h["in_battle"]
    snap = h["state_to_bytes"]
    btn_pair = h["btn_pair"]

    h["state_from_bytes"](GRASS_STATE.read_bytes())
    tick(4)
    if T:
        tick(T)

    window: collections.deque = collections.deque(maxlen=SNAPSHOT_WINDOW)
    frame_idx = 0

    def snap_tick() -> bool:
        """Snapshot current frame, advance one frame, return in_battle()."""
        nonlocal frame_idx
        window.append((frame_idx, snap()))
        tick(1)
        frame_idx += 1
        return in_battle()

    for step in range(MAX_STEPS_PER_WALK):
        if in_battle():
            return window
        button = btn_pair[step & 1]
        pyboy.button_press(button)
        for f in range(MANIP_WALK_HOLD):
            if snap_tick():
                pyboy.button_release(button)
                return window
            if f == MANIP_WALK_HOLD - 1:
                pyboy.button_release(button)
        for _ in range(MANIP_WALK_GAP):
            if snap_tick():
                return window
    return None


def probe_from_snapshot(pyboy: PyBoy, h, snapshot: bytes,
                        add: int, sub: int) -> tuple[int, int, object, bool]:
    """Load a snapshot, write (add, sub) to HRAM, tick into battle, settle,
    read enemy.  Returns (species, level, dvs, reached_battle)."""
    tick = h["tick"]
    in_battle = h["in_battle"]
    h["state_from_bytes"](snapshot)
    pyboy.memory[ADDR_H_RANDOM_ADD] = add & 0xFF
    pyboy.memory[ADDR_H_RANDOM_SUB] = sub & 0xFF

    reached = in_battle()
    for _ in range(BATTLE_TICK_BUDGET):
        if reached:
            break
        tick(1)
        reached = in_battle()
    tick(BATTLE_SETTLE)
    species, level, dvs = h["read_enemy"]()
    return species, level, dvs, reached


def find_pre_dv_in_window(pyboy: PyBoy, h, window) -> tuple[bytes, int, int, int] | None:
    """Backward-scan the snapshot window for the PRE_DV frame: the latest
    frame where writing hRandomSub still controls enemy DV byte-0 while
    the species stays fixed (i.e. past the species roll, before the DV
    roll).

    Returns (pre_dv_bytes, frame_idx, species, level) or None.
    """
    for frame_idx, snap in reversed(window):
        sp_a, lvl_a, dvs_a, ok_a = probe_from_snapshot(pyboy, h, snap, 0, SCAN_SUB_A)
        if not ok_a:
            continue
        sp_b, _, dvs_b, ok_b = probe_from_snapshot(pyboy, h, snap, 0, SCAN_SUB_B)
        if not ok_b:
            continue
        b0_a = (dvs_a.attack << 4) | dvs_a.defense
        b0_b = (dvs_b.attack << 4) | dvs_b.defense
        # Controls DVs (b0 changed) AND species already settled (unchanged).
        if b0_a != b0_b and sp_a == sp_b:
            return snap, frame_idx, sp_a, lvl_a
    return None


def build_pre_dv(pyboy: PyBoy, h, T: int) -> tuple[bytes, int, int] | None:
    """Build the PRE_DV state at offset T.  Returns (bytes, species, level)
    or None if no usable encounter was found."""
    window = walk_capturing_window(pyboy, h, T)
    if window is None:
        return None
    found = find_pre_dv_in_window(pyboy, h, window)
    if found is None:
        return None
    pre_dv, _frame_idx, species, level = found
    return pre_dv, species, level


# ────────────────────────────────────────────────────────────────────────
# Multi-offset target search
# ────────────────────────────────────────────────────────────────────────

def find_target_shiny(pyboy: PyBoy, h, max_offsets: int,
                      target_species: int | None, rom_sha1: str) -> int:
    target_b0s = target_b0s_for_filter(MIN_ATK_DV, MAX_ATK_DV)
    if not target_b0s:
        print(f"ERROR: ATK filter [{MIN_ATK_DV},{MAX_ATK_DV}] has no "
              f"shiny-eligible values ({SHINY_ATKS}).", file=sys.stderr)
        return 1
    targets_by_delta = {(0xAA - b0) & 0xFF: b0 for b0 in target_b0s}

    sp_name = ("any" if target_species is None
               else f"{SPECIES_NAMES.get(target_species, '?')} ({target_species})")
    print(f"[find] species filter: {sp_name}")
    print(f"[find] target DV byte-0: {[f'0x{b:02X}' for b in target_b0s]}  "
          f"(required deltas: {[f'0x{d:02X}' for d in targets_by_delta]})")

    deltas_seen: dict[int, int] = {}
    species_seen: dict[int, int] = {}
    start = time.monotonic()

    for T in range(max_offsets):
        if SHOULD_EXIT:
            break
        built = build_pre_dv(pyboy, h, T)
        if built is None:
            print(f"[find] T={T:>3}  no usable encounter — skip", file=sys.stderr)
            continue
        pre_dv, species, level = built
        species_seen[species] = species_seen.get(species, 0) + 1

        # Baseline probe at sub=0 to measure this state's fixed delta.
        sp0, lvl0, dvs0, ok0 = probe_from_snapshot(pyboy, h, pre_dv, 0, 0)
        if not ok0 or sp0 != species:
            print(f"[find] T={T:>3}  baseline unstable (sp {species}->{sp0}); skip",
                  file=sys.stderr)
            continue
        b0_base = (dvs0.attack << 4) | dvs0.defense
        b1_base = (dvs0.speed << 4) | dvs0.special
        delta = (b1_base - b0_base) & 0xFF
        deltas_seen.setdefault(delta, T)

        species_ok = (target_species is None) or (species == target_species)
        if T % 16 == 0 or (delta in targets_by_delta and species_ok):
            print(f"[find] T={T:>3}  {SPECIES_NAMES.get(species, species):>10} "
                  f"L{level:>2}  b0=0x{b0_base:02X} b1=0x{b1_base:02X}  "
                  f"delta=0x{delta:02X}  uniq-deltas={len(deltas_seen)}")

        if delta not in targets_by_delta or not species_ok:
            continue

        # Delta + species line up.  Compute the magic hRandomSub.
        target_b0 = targets_by_delta[delta]
        v = (target_b0 - b0_base) & 0xFF
        sp_v, lvl_v, dvs_v, ok_v = probe_from_snapshot(pyboy, h, pre_dv, 0, v)
        b0_got = (dvs_v.attack << 4) | dvs_v.defense
        b1_got = (dvs_v.speed << 4) | dvs_v.special
        if not ok_v or sp_v != species or b0_got != target_b0 or b1_got != 0xAA \
                or not is_shiny(dvs_v):
            print(f"[find] T={T:>3}  delta matched but verify failed "
                  f"(sp={sp_v} b0=0x{b0_got:02X} b1=0x{b1_got:02X}); continuing",
                  file=sys.stderr)
            continue

        elapsed = time.monotonic() - start
        name = SPECIES_NAMES.get(sp_v, f"???({sp_v})")
        print()
        print("=" * 60)
        print(f"  ✨  TARGET SHINY {name} (MANIP-DETERMINISTIC)  ✨")
        print(f"  offset T: {T}   hRandomSub: 0x{v:02X}   hRandomAdd: 0x00")
        print(f"  Level {lvl_v}  ATK={dvs_v.attack} DEF={dvs_v.defense} "
              f"SPD={dvs_v.speed} SPC={dvs_v.special}")
        print(f"  Found in {elapsed:.1f}s ({T + 1} offsets, "
              f"{len(deltas_seen)} unique deltas)")
        print("=" * 60)

        magic = ROOT / "roms" / f"shiny_grass_manip_T{T}_v{v:02X}.state"
        with open(magic, "wb") as f:
            f.write(pre_dv)
        print(f"Saved magic PRE_DV to {magic}")
        with open(SHINY_STATE, "wb") as f:
            pyboy.save_state(f)
        print(f"Saved in-battle state (enemy is the shiny) to {SHINY_STATE}")
        print(f"Reproduce: python shiny_grass_manip.py --replay-offset {T} --sub 0x{v:02X}")

        log_shiny_found(offset=T, rng_sub=v, species=sp_v, level=lvl_v,
                        dvs=dvs_v, target=True, target_species=target_species,
                        rom_sha1=rom_sha1, elapsed_s=elapsed)
        return 0

    print()
    print(f"[find] tried {min(max_offsets, T + 1)} offsets, no target found.")
    print(f"  Unique deltas seen: {len(deltas_seen)} / 256")
    print(f"  Required deltas: {[f'0x{d:02X}' for d in targets_by_delta]}")
    missing = [d for d in targets_by_delta if d not in deltas_seen]
    if missing:
        print(f"  Missing deltas: {[f'0x{d:02X}' for d in missing]} → raise --max-offsets")
    top = sorted(species_seen.items(), key=lambda kv: -kv[1])[:6]
    print(f"  Species rolled: "
          f"{', '.join(f'{SPECIES_NAMES.get(s, s)}:{c}' for s, c in top)}")
    return 0


# ────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()

    if args.stats:
        print_shiny_history(load_shiny_history())
        return 0

    if not GRASS_STATE.exists():
        print(f"ERROR: grass save state not found at {GRASS_STATE}", file=sys.stderr)
        print(file=sys.stderr)
        print("Create one before running this script:", file=sys.stderr)
        print("  1. python play.py", file=sys.stderr)
        print("  2. Stand on an encounter tile with a clear adjacent tile", file=sys.stderr)
        print(f"     along MOVE_AXIS={MOVE_AXIS!r} (so oscillation can step).", file=sys.stderr)
        print("  3. Shift+1 to save to slot 1, close the window, then:", file=sys.stderr)
        print(f"     mv roms/pokemon_gold.gbc.state1 {GRASS_STATE}", file=sys.stderr)
        return 1

    axis = args.axis if args.axis is not None else MOVE_AXIS
    if args.species is None:
        target_species: int | None = TARGET_SPECIES
    elif args.species == -1:
        target_species = None
    else:
        target_species = args.species

    rom_sha1 = file_sha1(ROM)
    print_shiny_history(load_shiny_history())
    print()
    print(f"ROM sha1={rom_sha1[:12]}…  grass_state sha1={file_sha1(GRASS_STATE)[:12]}…")
    print(f"Filter: ATK∈[{MIN_ATK_DV},{MAX_ATK_DV}]  axis={axis!r}  "
          f"species={'any' if target_species is None else target_species}")

    pyboy = PyBoy(str(ROM), window="null" if HEADLESS else "SDL2")
    try:
        pyboy.sound_emulated = False
    except AttributeError:
        pass
    pyboy.set_emulation_speed(0)

    total_frames = [0]
    h = make_helpers(pyboy, total_frames, axis)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        if args.build_state:
            built = build_pre_dv(pyboy, h, 0)
            if built is None:
                print("[build] no usable encounter found at T=0.", file=sys.stderr)
                return 1
            pre_dv, species, level = built
            with open(PRE_DV_STATE, "wb") as f:
                f.write(pre_dv)
            sp0, lvl0, dvs0, _ = probe_from_snapshot(pyboy, h, pre_dv, 0, 0)
            b0 = (dvs0.attack << 4) | dvs0.defense
            b1 = (dvs0.speed << 4) | dvs0.special
            delta = (b1 - b0) & 0xFF
            print(f"[build] PRE_DV written to {PRE_DV_STATE}")
            print(f"[build] species={SPECIES_NAMES.get(species, species)} L{level}  "
                  f"baseline b0=0x{b0:02X} b1=0x{b1:02X}  delta=0x{delta:02X}")
            return 0

        if args.probe is not None:
            built = build_pre_dv(pyboy, h, 0)
            if built is None:
                print("[probe] no usable encounter at T=0.", file=sys.stderr)
                return 1
            pre_dv, _, _ = built
            add, sub = args.probe
            sp, lvl, dvs, ok = probe_from_snapshot(pyboy, h, pre_dv, add, sub)
            name = SPECIES_NAMES.get(sp, f"???({sp})")
            print(f"probe T=0  add=0x{add:02X} sub=0x{sub:02X}  reached_battle={ok}")
            print(f"  {name} L{lvl}  ATK={dvs.attack} DEF={dvs.defense} "
                  f"SPD={dvs.speed} SPC={dvs.special} "
                  f"{'shiny' if is_shiny(dvs) else 'not shiny'}")
            return 0

        if args.replay_offset is not None:
            built = build_pre_dv(pyboy, h, args.replay_offset)
            if built is None:
                print(f"[replay] no usable encounter at T={args.replay_offset}.",
                      file=sys.stderr)
                return 1
            pre_dv, _, _ = built
            sp, lvl, dvs, ok = probe_from_snapshot(pyboy, h, pre_dv, 0, args.sub)
            name = SPECIES_NAMES.get(sp, f"???({sp})")
            print(f"replay T={args.replay_offset} sub=0x{args.sub:02X}  "
                  f"reached_battle={ok}")
            print(f"  {name} L{lvl}  ATK={dvs.attack} DEF={dvs.defense} "
                  f"SPD={dvs.speed} SPC={dvs.special} "
                  f"{'shiny' if is_shiny(dvs) else 'not shiny'}")
            if is_shiny(dvs):
                with open(SHINY_STATE, "wb") as f:
                    pyboy.save_state(f)
                print(f"  saved in-battle state to {SHINY_STATE}")
            return 0

        # Default: find a target shiny.
        return find_target_shiny(pyboy, h, args.max_offsets, target_species, rom_sha1)

    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 0
    finally:
        pyboy.stop(save=False)


if __name__ == "__main__":
    sys.exit(main())
