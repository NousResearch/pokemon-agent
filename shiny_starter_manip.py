"""Deterministic-RNG-write Totodile starter farm.

This is the working version of the abandoned 91e99c5 manipulation
attempt.  Key insight: with a save state captured *just before* the
DV-gen Random() calls, the mapping (hRandomAdd_write, hRandomSub_write)
→ final_DVs is a deterministic function — every intervening Random()
call happens at known rDIV phases because PyBoy save_state captures
rDIV.  So we can sweep (add, sub) ∈ [0, 65535] with guaranteed
coverage and zero birthday-paradox waste.

Two phases
----------
A) **Calibration (one-time)** — build ``roms/pokemon_gold.gbc.pre_dv.state``:
   1. From the pre-Pokeball state, mash A through dialog, saving an
      in-memory snapshot before each press.  The press that flips
      party_count to 1 is the YES press; the snapshot just before it
      is the Y/N-menu state.
   2. From the Y/N state, press A and tick frame-by-frame, snapshotting
      each frame.  The frame whose tick first flips party_count is the
      DV-gen frame; the snapshot taken just before that tick is the
      PRE_DV state — load this, the very next tick generates DVs.

B) **Sweep loop** — for each attempt:
   1. ``load_state(pre_dv_state)``
   2. Write (add, sub) per the attempt's stride-spaced sweep
   3. Verify the write stuck via read-back
   4. Tick a small budget of frames until party_count > 0
   5. Read DVs; if target, save state + report magic (add, sub) + exit

If after a full 65536-attempt sweep no target is found, we dump the
(add, sub) → DV mapping to ``manip_lookup.json`` and exit so you can
inspect what's reachable from this PRE_DV state.

Run with the project venv active:
    source .venv/bin/activate
    python shiny_starter_manip.py                       # build state if missing, then sweep
    python shiny_starter_manip.py --build-state         # rebuild calibration state
    python shiny_starter_manip.py --stats               # show manip shiny history
    python shiny_starter_manip.py --probe 0xCAFE 0x1234 # one-shot: load state, write bytes, read DVs
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import secrets
import signal
import sys
import time
from pathlib import Path

from pyboy import PyBoy

from pokemon_agent.memory.gold import (
    ADDR_JOY_LOCK,
    ADDR_PARTY_COUNT,
    ADDR_PARTY_MON1,
    ADDR_TEXT_DELAY,
    PARTYMON_OFF_DVS,
    PARTYMON_OFF_SPECIES,
    SPECIES_NAMES,
)
from pokemon_agent.shiny import decode_dvs, is_shiny

ROOT = Path(__file__).resolve().parent
ROM = ROOT / "roms" / "pokemon_gold.gbc"
PRE_STATE = ROOT / "roms" / "pokemon_gold.gbc.state"
PRE_DV_STATE = ROOT / "roms" / "pokemon_gold.gbc.pre_dv.state"
SHINY_STATE = ROOT / "roms" / "shiny_totodile_manip.state"
DV_LOG_PATH = ROOT / "manip_dv_log.jsonl"
SHINY_LOG_PATH = ROOT / "manip_shinies.jsonl"
LOOKUP_PATH = ROOT / "manip_lookup.json"

TOTODILE_ID = 158

SPEED = "FAST"
HEADLESS = True

# Target filter — same shape as shiny_starter.py.
MIN_ATK_DV = 15
MAX_ATK_DV = 15

# Calibration budgets.
MAX_PRESSES_TO_PARTY_FILL = 80
MAX_FRAMES_PER_PRESS = 80   # frames we tick after pressing A before declaring stuck
DIALOG_WAIT_MAX = 240

# Press timing — needs to match the timing used in calibration so the
# (state, write) → DV function stays stable.
A_HOLD = 3
PRESS_GAP = 4
MIN_PRESS_INTERVAL = 10

# Sweep loop frame budget per attempt.  PRE_DV state should fill the
# party within 1-3 ticks; 32 is generous.
SWEEP_TICK_BUDGET = 32

# Print a throughput line every N attempts.
THROUGHPUT_INTERVAL = 100

# Gen-2 RNG state in HRAM.
# Correct addresses (verified against pret/pokegold + TASvideos Gen-2 RNG page):
#   Gold/Silver: hRandomAdd=0xFFE3, hRandomSub=0xFFE4
#   Crystal:     hRandomAdd=0xFFE1, hRandomSub=0xFFE2
# The previous commits in this repo used 0xFFD9/0xFFDA — that was wrong
# for both versions and is why the 91e99c5/24115e1/f9665dc attempts
# never produced deterministic DVs.  hRandomSub is the byte Random()
# *returns* (used as the DV byte directly), so it's the one that
# matters most.
ADDR_H_RANDOM_ADD = 0xFFE3
ADDR_H_RANDOM_SUB = 0xFFE4
ADDR_DIV = 0xFF04

# Stride coprime to 2^16; jumps the byte split per attempt so we don't
# crawl one nibble at a time.
RNG_STRIDE = 65521
RNG_SWEEP_TOTAL = 65536

SHOULD_EXIT = False


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
        print("Manip shiny history: (none yet)")
        return
    targets = [s for s in history if s.get("target")]
    print(f"Manip shiny history: {len(history)} total, {len(targets)} matching the current filter")
    for s in history[-10:]:
        marker = "TARGET" if s.get("target") else "      "
        iso = s.get("iso", "?")
        print(
            f"  {marker}  {iso}  attempt={s.get('attempt'):>6}  "
            f"add=0x{s.get('rng_add', 0):02X} sub=0x{s.get('rng_sub', 0):02X} "
            f"ATK={s.get('atk'):2} DEF={s.get('def'):2} "
            f"SPD={s.get('spd'):2} SPC={s.get('spc'):2}"
        )


def _signal_handler(sig: int, _frame) -> None:
    global SHOULD_EXIT
    if SHOULD_EXIT:
        print("\nForced exit.", file=sys.stderr)
        sys.exit(1)
    print("\nSIGINT — finishing current attempt then exiting...", file=sys.stderr)
    SHOULD_EXIT = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pokemon Gold deterministic-RNG-write starter farm.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--build-state", action="store_true",
                   help="Rebuild the PRE_DV calibration state and exit.")
    p.add_argument("--stats", action="store_true",
                   help="Print cumulative manip shiny history and exit.")
    p.add_argument("--probe", nargs=2, type=lambda s: int(s, 0), default=None,
                   metavar=("ADD", "SUB"),
                   help="One-shot probe: load PRE_DV, write the given (add, sub), "
                        "read DVs, print and exit.  Useful for verifying determinism.")
    p.add_argument("--start-offset", type=lambda s: int(s, 0), default=None,
                   help="Override the starting (add, sub) offset for the sweep.  "
                        "Default = random per-run.")
    p.add_argument("--find-target", action="store_true",
                   help="Multi-frame-offset deterministic search for any shiny "
                        "in the current ATK filter.  Tries up to "
                        "--max-offsets tick offsets, each producing a different "
                        "rDIV phase at DV-gen.  Stops at first hit.")
    p.add_argument("--max-offsets", type=int, default=256,
                   help="Upper bound on tick offsets to try in --find-target mode.")
    return p.parse_args(argv)


def log_shiny_found(*, attempt: int, dvs, target: bool, rng_add: int,
                    rng_sub: int, rom_sha1: str, state_sha1: str,
                    elapsed_s: float, run_frames: int) -> None:
    entry = {
        "ts": time.time(),
        "iso": datetime.datetime.now().isoformat(timespec="seconds"),
        "attempt": attempt,
        "atk": dvs.attack, "def": dvs.defense,
        "spd": dvs.speed, "spc": dvs.special,
        "raw_dvs": f"0x{dvs.raw:04x}",
        "shiny": True, "target": bool(target),
        "min_atk": MIN_ATK_DV, "max_atk": MAX_ATK_DV,
        "rng_add": rng_add, "rng_sub": rng_sub,
        "elapsed_s": round(elapsed_s, 2),
        "run_frames": run_frames,
        "rom_sha1": rom_sha1, "state_sha1": state_sha1,
        "reproduce": (f"python shiny_starter_manip.py --probe "
                      f"0x{rng_add:02X} 0x{rng_sub:02X}"),
    }
    try:
        with open(SHINY_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"  warning: failed to write {SHINY_LOG_PATH}: {e}", file=sys.stderr)


# ────────────────────────────────────────────────────────────────────────
# helpers that close over pyboy + counters (constructed in main())
# ────────────────────────────────────────────────────────────────────────

def make_helpers(pyboy: PyBoy, frame_count: list[int], total_frames: list[int]):
    def tick(n: int = 1) -> None:
        for _ in range(n):
            if SHOULD_EXIT:
                raise KeyboardInterrupt()
            if not pyboy.tick(render=False):
                sys.exit(0)
            frame_count[0] += 1
            total_frames[0] += 1

    def press(button: str, hold: int = A_HOLD, gap: int = PRESS_GAP) -> None:
        pyboy.button_press(button)
        tick(hold)
        pyboy.button_release(button)
        tick(gap)

    def read_u8(addr: int) -> int:
        return pyboy.memory[addr] & 0xFF

    def party_count() -> int:
        return read_u8(ADDR_PARTY_COUNT)

    def dialog_active() -> bool:
        return read_u8(ADDR_JOY_LOCK) != 0 or read_u8(ADDR_TEXT_DELAY) != 0

    def wait_input_ready(max_frames: int = DIALOG_WAIT_MAX) -> None:
        for _ in range(max_frames // 4):
            if not dialog_active():
                return
            tick(4)

    def state_to_bytes() -> bytes:
        buf = io.BytesIO()
        pyboy.save_state(buf)
        return buf.getvalue()

    def state_from_bytes(b: bytes) -> None:
        pyboy.load_state(io.BytesIO(b))

    return tick, press, read_u8, party_count, dialog_active, wait_input_ready, state_to_bytes, state_from_bytes


# ────────────────────────────────────────────────────────────────────────
# Phase A — build PRE_DV calibration state
# ────────────────────────────────────────────────────────────────────────

def build_yn_state_bytes(pyboy: PyBoy, helpers) -> bytes:
    """From PRE_STATE, mash A through dialog and return the in-memory
    snapshot taken just before the press that fills the party.

    That snapshot — known as the YN state — is the latest deterministic
    overworld-idle point before DV generation runs.  All multi-frame
    offset searches branch from here.
    """
    tick, press, _, party_count, _, wait_input_ready, state_to_bytes, state_from_bytes = helpers

    if not PRE_STATE.exists():
        raise FileNotFoundError(f"need pre-Pokeball state at {PRE_STATE}")

    state_from_bytes(PRE_STATE.read_bytes())
    tick(4)

    yn_state: bytes | None = None
    for press_idx in range(MAX_PRESSES_TO_PARTY_FILL):
        pc = party_count()
        if pc > 0:
            raise RuntimeError("party already filled at calibration start; "
                               "PRE_STATE looks wrong")
        before = state_to_bytes()
        wait_input_ready()
        press("a")
        tick(MIN_PRESS_INTERVAL)
        if party_count() > 0:
            yn_state = before
            return yn_state
    raise RuntimeError(f"never filled party after {MAX_PRESSES_TO_PARTY_FILL} presses")


def build_pre_dv_from_yn(pyboy: PyBoy, helpers, yn_state_bytes: bytes,
                        pre_press_ticks: int = 0) -> bytes | None:
    """Build a PRE_DV save state by replaying the YES press from yn_state,
    optionally with *pre_press_ticks* extra idle ticks beforehand so the
    rDIV phase at DV-gen call shifts.

    Returns the in-memory PRE_DV bytes (state captured 1 tick before
    party_count flips) or None if the press didn't fill within budget.
    """
    tick, _, _, party_count, _, _, state_to_bytes, state_from_bytes = helpers
    state_from_bytes(yn_state_bytes)
    if pre_press_ticks:
        tick(pre_press_ticks)

    pyboy.button_press("a")
    button_released = False
    snapshots: list[bytes] = []
    for f in range(MAX_FRAMES_PER_PRESS):
        snapshots.append(state_to_bytes())
        tick(1)
        if not button_released and f >= A_HOLD:
            pyboy.button_release("a")
            button_released = True
        if party_count() > 0:
            return snapshots[-1]
    if not button_released:
        pyboy.button_release("a")
    return None


def build_pre_dv_state(pyboy: PyBoy, helpers) -> None:
    """Public entry point matching the old --build-state behavior: build
    YN, then PRE_DV at offset 0, write to disk."""
    print(f"[build] loading pre-Pokeball state from {PRE_STATE}")
    print(f"[build] phase A1: walking dialog to find Y/N state...")
    yn_state = build_yn_state_bytes(pyboy, helpers)
    print(f"[build] YN captured ({len(yn_state)} bytes)")

    print(f"[build] phase A2: ticking from YN to find PRE_DV frame...")
    pre_dv_state = build_pre_dv_from_yn(pyboy, helpers, yn_state, pre_press_ticks=0)
    if pre_dv_state is None:
        raise RuntimeError(f"party didn't fill within {MAX_FRAMES_PER_PRESS} frames")
    print(f"[build] PRE_DV captured ({len(pre_dv_state)} bytes)")

    with open(PRE_DV_STATE, "wb") as f:
        f.write(pre_dv_state)
    print(f"[build] wrote {len(pre_dv_state)} bytes to {PRE_DV_STATE}")
    print(f"[build] PRE_DV sha1={file_sha1(PRE_DV_STATE)[:12]}…")


# ────────────────────────────────────────────────────────────────────────
# Phase C — multi-frame-offset target search
# ────────────────────────────────────────────────────────────────────────

# All Gen-2 shiny-eligible ATK values.
SHINY_ATKS = (2, 3, 6, 7, 10, 11, 14, 15)


def target_b0s_for_filter(min_atk: int, max_atk: int) -> list[int]:
    """The DV byte-0 values that satisfy (shiny + ATK in [min, max])."""
    return [atk * 16 + 10 for atk in SHINY_ATKS if min_atk <= atk <= max_atk]


def find_target_shiny(pyboy: PyBoy, helpers, max_offsets: int = 256) -> None:
    """Multi-frame-offset deterministic search for any shiny in the
    current ATK filter.

    For each tick offset T:
      1. Build PRE_DV at offset T (different rDIV phase at DV gen).
      2. Single probe at (add=0, sub=0) → measure baseline (DV0_0, DV1_0).
      3. Delta = (DV1_0 - DV0_0) mod 256 is constant for this state.
      4. For each shiny ATK X in our filter, the required delta is
         (0xAA - (X*16+10)) mod 256.  If our delta matches, compute
         v = (target_DV0 - DV0_0) mod 256 — that's the magic hRandomSub.
      5. Verify the magic value, save state + report, exit.

    Total cost: ≤256 PRE_DV builds + ≤2 probes/offset.  Each PRE_DV
    build is ~10 frames + a few snapshots; each probe is ~24 frames.
    Wall time: roughly 30 seconds on this rig.
    """
    print("[find] building YN state...")
    yn_state = build_yn_state_bytes(pyboy, helpers)

    target_b0s = target_b0s_for_filter(MIN_ATK_DV, MAX_ATK_DV)
    if not target_b0s:
        print(f"ERROR: ATK filter [{MIN_ATK_DV},{MAX_ATK_DV}] contains no "
              f"shiny-eligible values ({SHINY_ATKS}).", file=sys.stderr)
        return
    targets_by_delta = {(0xAA - b0) & 0xFF: b0 for b0 in target_b0s}
    print(f"[find] hunting target DV byte-0 values: "
          f"{[f'0x{b:02X}' for b in target_b0s]}  "
          f"(required deltas: {[f'0x{d:02X}' for d in targets_by_delta]})")

    deltas_seen: dict[int, int] = {}  # delta → first T that produced it
    start = time.monotonic()

    for T in range(max_offsets):
        if SHOULD_EXIT:
            break

        pre_dv = build_pre_dv_from_yn(pyboy, helpers, yn_state, pre_press_ticks=T)
        if pre_dv is None:
            print(f"[find] T={T:>3}  party didn't fill — skipping", file=sys.stderr)
            continue

        species, dvs, stuck, frames = run_attempt(pyboy, helpers, pre_dv, 0, 0)
        if species != TOTODILE_ID:
            print(f"[find] T={T:>3}  wrong species ({species}); skip", file=sys.stderr)
            continue
        b0_base = (dvs.attack << 4) | dvs.defense
        b1_base = (dvs.speed << 4) | dvs.special
        delta = (b1_base - b0_base) & 0xFF
        if delta not in deltas_seen:
            deltas_seen[delta] = T

        if T % 16 == 0 or delta in targets_by_delta:
            print(f"[find] T={T:>3}  baseline (b0=0x{b0_base:02X}, b1=0x{b1_base:02X})  "
                  f"delta=0x{delta:02X}  unique-deltas={len(deltas_seen)}")

        if delta not in targets_by_delta:
            continue

        # Target reachable from this state.  Compute the magic v.
        target_b0 = targets_by_delta[delta]
        v = (target_b0 - b0_base) & 0xFF

        # Verify
        species, dvs, stuck, frames = run_attempt(pyboy, helpers, pre_dv, 0, v)
        b0_got = (dvs.attack << 4) | dvs.defense
        b1_got = (dvs.speed << 4) | dvs.special
        if b0_got != target_b0 or b1_got != 0xAA:
            print(f"[find] T={T:>3}  delta matched but verify failed "
                  f"(got b0=0x{b0_got:02X} b1=0x{b1_got:02X}, "
                  f"wanted b0=0x{target_b0:02X} b1=0xAA).  "
                  f"Probably a carry-edge case; continuing.", file=sys.stderr)
            continue
        if not is_shiny(dvs):
            print(f"[find] T={T:>3}  verify produced non-shiny DVs?? continuing",
                  file=sys.stderr)
            continue

        # Success.
        elapsed = time.monotonic() - start
        print()
        print("=" * 60)
        print(f"  ✨  TARGET SHINY TOTODILE (MANIP-DETERMINISTIC)  ✨")
        print(f"  T (pre-YES tick offset): {T}")
        print(f"  hRandomAdd write: 0x00")
        print(f"  hRandomSub write: 0x{v:02X}")
        print(f"  DVs: ATK={dvs.attack}  DEF={dvs.defense}  "
              f"SPD={dvs.speed}  SPC={dvs.special}")
        print(f"  Found in {elapsed:.1f}s ({T + 1} tick offsets tried, "
              f"{len(deltas_seen)} unique deltas)")
        print("=" * 60)

        # Save the PRE_DV state and the in-battle/in-party state.
        magic_state_path = ROOT / "roms" / f"shiny_totodile_manip_T{T}_v{v:02X}.state"
        with open(magic_state_path, "wb") as f:
            f.write(pre_dv)
        print(f"Saved magic PRE_DV to {magic_state_path}")
        with open(SHINY_STATE, "wb") as f:
            pyboy.save_state(f)
        print(f"Saved post-DV state (party has the shiny) to {SHINY_STATE}")

        log_shiny_found(
            attempt=T + 1, dvs=dvs, target=True,
            rng_add=0, rng_sub=v,
            rom_sha1=file_sha1(ROM), state_sha1=file_sha1(PRE_DV_STATE) if PRE_DV_STATE.exists() else "",
            elapsed_s=elapsed, run_frames=0,
        )
        return

    # No hit in max_offsets.
    print()
    print(f"[find] tried {max_offsets} tick offsets, no target found.")
    print(f"  Unique deltas seen: {len(deltas_seen)} / 256 possible.")
    print(f"  Required deltas were: {[f'0x{d:02X}' for d in targets_by_delta]}")
    missing = [d for d in targets_by_delta if d not in deltas_seen]
    if missing:
        print(f"  Missing: {[f'0x{d:02X}' for d in missing]}")
        print(f"  → Increase --max-offsets or widen ATK filter.")
    else:
        print(f"  All target deltas were seen but each verify failed.")
        print(f"  Likely a carry-flag edge case; needs deeper investigation.")


# ────────────────────────────────────────────────────────────────────────
# Phase B — sweep (add, sub) and look for target DVs
# ────────────────────────────────────────────────────────────────────────

def run_attempt(pyboy, helpers, pre_dv_bytes: bytes, add: int, sub: int) -> tuple:
    """One attempt: load PRE_DV → write (add, sub) → tick → read DVs.

    Returns (species, dvs, write_stuck, frames_to_fill).
    """
    tick, press, read_u8, party_count, _, wait_input_ready, state_to_bytes, state_from_bytes = helpers

    state_from_bytes(pre_dv_bytes)
    # Write our RNG bytes.  Verify the write actually landed.
    pyboy.memory[ADDR_H_RANDOM_ADD] = add & 0xFF
    pyboy.memory[ADDR_H_RANDOM_SUB] = sub & 0xFF
    got_add = read_u8(ADDR_H_RANDOM_ADD)
    got_sub = read_u8(ADDR_H_RANDOM_SUB)
    write_stuck = (got_add == add & 0xFF and got_sub == sub & 0xFF)

    # Tick until party fills, then a few extra ticks so the engine
    # has time to write the DV bytes into the slot (party_count flips
    # before slot 0's DV bytes are populated).
    frames = 0
    filled_at = -1
    for _ in range(SWEEP_TICK_BUDGET):
        tick(1)
        frames += 1
        if party_count() > 0:
            filled_at = frames
            break
    # Settle for DV writes — empirically ~4 frames is enough.
    tick(8)
    frames += 8
    base = ADDR_PARTY_MON1
    species = read_u8(base + PARTYMON_OFF_SPECIES)
    b0 = read_u8(base + PARTYMON_OFF_DVS)
    b1 = read_u8(base + PARTYMON_OFF_DVS + 1)
    dvs = decode_dvs(b0, b1)
    return species, dvs, write_stuck, frames


def sweep_loop(pyboy, helpers, pre_dv_bytes, rom_sha1, state_sha1, start_offset):
    tick, *_ = helpers

    dv_log = open(DV_LOG_PATH, "a", buffering=1)
    lookup: dict[int, int] = {}  # packed_input (add<<8|sub) → packed_dvs
    count_shiny = count_target = count_write_failed = count_wrong_species = 0
    start_time = time.monotonic()
    total_frames = 0

    print(f"[sweep] starting; offset=0x{start_offset:04X}, stride={RNG_STRIDE}, "
          f"total {RNG_SWEEP_TOTAL} unique (add, sub) pairs")

    for attempt in range(1, RNG_SWEEP_TOTAL + 1):
        if SHOULD_EXIT:
            break
        n = (start_offset + (attempt - 1) * RNG_STRIDE) & 0xFFFF
        add = (n >> 8) & 0xFF
        sub = n & 0xFF

        species, dvs, write_stuck, frames = run_attempt(
            pyboy, helpers, pre_dv_bytes, add, sub)
        total_frames += frames

        if not write_stuck:
            count_write_failed += 1

        if species != TOTODILE_ID:
            count_wrong_species += 1
            species_name = SPECIES_NAMES.get(species, f"???({species})")
            print(f"[{attempt:>5}] WRONG SPECIES: {species_name} ({species}); skipping",
                  file=sys.stderr)
            continue

        shiny = is_shiny(dvs)
        atk_ok = MIN_ATK_DV <= dvs.attack <= MAX_ATK_DV
        target = shiny and atk_ok
        if shiny:
            count_shiny += 1
        if target:
            count_target += 1

        lookup[n] = dvs.raw
        dv_log.write(
            f'{{"a":{attempt},"add":{add},"sub":{sub},'
            f'"atk":{dvs.attack},"def":{dvs.defense},'
            f'"spd":{dvs.speed},"spc":{dvs.special},'
            f'"shiny":{int(shiny)},"target":{int(target)}}}\n'
        )

        if target:
            print()
            print("=" * 60)
            elapsed = time.monotonic() - start_time
            print(f"  ✨  TARGET SHINY TOTODILE (MANIP)  ✨   on attempt {attempt}")
            print(f"  add=0x{add:02X} sub=0x{sub:02X}")
            print(f"  DVs:  ATK={dvs.attack}  DEF={dvs.defense}  "
                  f"SPD={dvs.speed}  SPC={dvs.special}")
            print(f"  Elapsed: {elapsed:.1f}s ({attempt} attempts)")
            print(f"  Reproduce: python shiny_starter_manip.py "
                  f"--probe 0x{add:02X} 0x{sub:02X}")
            print("=" * 60)
            log_shiny_found(attempt=attempt, dvs=dvs, target=target,
                            rng_add=add, rng_sub=sub,
                            rom_sha1=rom_sha1, state_sha1=state_sha1,
                            elapsed_s=elapsed, run_frames=total_frames)
            with open(SHINY_STATE, "wb") as f:
                pyboy.save_state(f)
            print(f"Saved shiny state to {SHINY_STATE}")
            dv_log.close()
            return

        if shiny:
            elapsed = time.monotonic() - start_time
            log_shiny_found(attempt=attempt, dvs=dvs, target=False,
                            rng_add=add, rng_sub=sub,
                            rom_sha1=rom_sha1, state_sha1=state_sha1,
                            elapsed_s=elapsed, run_frames=total_frames)
            print(f"[{attempt:>5}] non-target shiny: add=0x{add:02X} sub=0x{sub:02X} "
                  f"ATK={dvs.attack} DEF={dvs.defense} SPD={dvs.speed} SPC={dvs.special}")

        if attempt % THROUGHPUT_INTERVAL == 0:
            elapsed = time.monotonic() - start_time
            rate = attempt / elapsed if elapsed > 0 else 0.0
            print(
                f"[{attempt:>5}] rate: {rate:.2f} a/s  "
                f"shinies: {count_shiny} (exp {attempt/8192:.2f})  "
                f"targets: {count_target}  "
                f"write-failed: {count_write_failed}  "
                f"wrong-species: {count_wrong_species}  "
                f"lookup size: {len(lookup)}"
            )

    dv_log.close()

    if count_target == 0:
        print()
        print("=" * 60)
        print(f"Sweep complete: {RNG_SWEEP_TOTAL} attempts, 0 targets found.")
        print(f"  Non-target shinies seen: {count_shiny}")
        print(f"  Dumping (add, sub) → DV lookup to {LOOKUP_PATH}")
        with open(LOOKUP_PATH, "w") as f:
            json.dump({str(k): v for k, v in lookup.items()}, f)
        print(f"  {len(lookup)} entries written")
        print("=" * 60)


def main() -> int:
    args = parse_args()

    if args.stats:
        print_shiny_history(load_shiny_history())
        return 0

    pyboy = PyBoy(str(ROM), window="null" if HEADLESS else "SDL2")
    try:
        pyboy.sound_emulated = False
    except AttributeError:
        pass
    pyboy.set_emulation_speed(0)

    frame_count = [0]
    total_frames = [0]
    helpers = make_helpers(pyboy, frame_count, total_frames)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        if args.find_target:
            find_target_shiny(pyboy, helpers, max_offsets=args.max_offsets)
            return 0

        if args.build_state or not PRE_DV_STATE.exists():
            build_pre_dv_state(pyboy, helpers)
            if args.build_state:
                print("[build] done.")
                return 0

        pre_dv_bytes = PRE_DV_STATE.read_bytes()
        rom_sha1 = file_sha1(ROM)
        state_sha1 = file_sha1(PRE_DV_STATE)
        print(f"ROM sha1={rom_sha1[:12]}…  PRE_DV sha1={state_sha1[:12]}…")

        if args.probe is not None:
            add, sub = args.probe
            species, dvs, stuck, frames = run_attempt(
                pyboy, helpers, pre_dv_bytes, add, sub)
            sname = SPECIES_NAMES.get(species, f"???({species})")
            print(f"probe: add=0x{add:02X} sub=0x{sub:02X}  "
                  f"write_stuck={stuck}  frames_to_fill={frames}")
            print(f"       {sname}  ATK={dvs.attack} DEF={dvs.defense} "
                  f"SPD={dvs.speed} SPC={dvs.special} "
                  f"{'shiny' if is_shiny(dvs) else 'not shiny'}")
            return 0

        if args.start_offset is None:
            start_offset = secrets.randbits(16)
        else:
            start_offset = args.start_offset & 0xFFFF

        sweep_loop(pyboy, helpers, pre_dv_bytes, rom_sha1, state_sha1, start_offset)

    except KeyboardInterrupt:
        print(file=sys.stderr)
    finally:
        pyboy.stop(save=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
