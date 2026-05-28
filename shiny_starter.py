"""Pokemon Gold shiny-starter farm for Totodile.

Repeatedly loads a save state placed in front of Prof Elm's starter
Pokeballs, picks Totodile, and reads party-slot-0 DVs the instant the
party fills.  On non-shiny attempts we reload immediately — no nickname
typing, no Elm follow-up dialog — saving ~2350 frames vs. running the
full sequence every loop.  Only on a target shiny do we advance the
rest of the dialog, type "KIWI", and snapshot the state.

Every shiny found (target or not) is logged to ``shinies.jsonl`` with
the master seed, attempt index, and DV/timing data needed to reproduce
the exact roll via ``--replay-attempt N --master-seed 0x...``.

What actually changes DVs between attempts is mix_rng() — see its
docstring.  Press patterns are OS-entropy-driven; idle ticks within
mix_rng matter too because the game's VBlank handler stirs rDIV into
the RNG state every frame.

Run with the project venv active:
    source .venv/bin/activate
    python shiny_starter.py

    # Show cumulative shiny history without launching the emulator:
    python shiny_starter.py --stats

    # Reproduce a previously-found shiny by its (master_seed, attempt):
    python shiny_starter.py --master-seed 0xDEADBEEFCAFEBABE --replay-attempt 4242
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
    ADDR_GAME_STATE,
    ADDR_JOY_LOCK,
    ADDR_PARTY_COUNT,
    ADDR_PARTY_MON1,
    ADDR_PARTY_NICKS,
    ADDR_PARTY_SPECIES,
    ADDR_TEXT_DELAY,
    GEN2_ENCODING,
    NAME_SIZE,
    PARTY_MON_SIZE,
    PARTYMON_OFF_DVS,
    PARTYMON_OFF_SPECIES,
    SPECIES_NAMES,
)
from pokemon_agent.shiny import decode_dvs, is_shiny

ROOT = Path(__file__).resolve().parent
ROM = ROOT / "roms" / "pokemon_gold.gbc"
STATE = ROOT / "roms" / "pokemon_gold.gbc.state"
SHINY_STATE = ROOT / "roms" / "shiny_totodile_kiwi.state"
# Append-only JSONL log of (attempt, species, DVs) so we can audit the
# empirical distribution offline. Cheap — one line-buffered write per
# attempt, ~70 B/line, ~50 KB/hour at 12 attempts/sec.
DV_LOG_PATH = ROOT / "shiny_dv_log.jsonl"
# Append-only JSONL log of every shiny found (target or not). Includes
# everything needed to reproduce the roll: master seed, attempt index,
# ROM + save-state hashes. Survives across runs.
SHINY_LOG_PATH = ROOT / "shinies.jsonl"

TOTODILE_ID = 158

# ── Run mode ────────────────────────────────────────────────────────────
# SPEED:
#   "FAST" — emulation_speed=0, no per-press debug output. This is the
#            mode the actual farming loop runs in.
#   "SLOW" — emulation_speed=1 (normal speed), prints raw joy_lock /
#            text_delay / party_count values around each press so you
#            can watch where detection is failing.
# DUMP_MEMORY:
#   True   — dump a few dozen bytes around the party / dialog WRAM
#            region whenever party_count first becomes > 0, and also on
#            phase-1 timeout. Pairs well with SLOW for diagnosing the
#            "party never fills" failure.
# HEADLESS:
#   True   — window="null"; no SDL2 window, no rendering work, MUCH
#            faster at emulation_speed=0.  Recommended for farming.
#   False  — window="SDL2"; visible window for debugging.
SPEED = "FAST"
DUMP_MEMORY = False
HEADLESS = True

# ── Shiny target filter ────────────────────────────────────────────────
# Only accept a shiny whose ATK DV falls in [MIN_ATK_DV, MAX_ATK_DV].
# Gen-2 shinies require DEF=SPD=SPC=10 and ATK ∈ {2,3,6,7,10,11,14,15};
# of those, 14 and 15 are the highest-ATK shinies.  Tighten this range
# to keep hunting for a better roll than a previously-found shiny.
MIN_ATK_DV = 15
MAX_ATK_DV = 15

# Bounds for each phase.  These are pressed-with-dialog-aware-waits, so
# a "press" here means "wait for joy_lock to clear, then tap A".  Counts
# are generous; extras after we've already reached the next state are
# either harmless (no-op on a stable menu) or self-correct on the next
# iteration of the outer loop.
MAX_PRESSES_TO_PARTY_FILL = 80     # Pokeball interact + "want this?" YES
# After party fill, the Totodile starter flow needs exactly:
#   press 1-3:  advance cry / "received TOTODILE!" / Elm flavor text
#   press 4:    YES on the "give a nickname?" Y/N menu → keyboard opens
# Frame-level traces show the keyboard is ready by the end of press 4.
# Any *additional* A-press lands on the keyboard with the cursor still
# at (0,0)='A' and types a stray 'A' — that's where "AAAAKIWI" came
# from when this used to be 8.
PRESSES_PARTY_TO_KEYBOARD = 4
PRESSES_POST_NICKNAME = 40         # Elm's "TOTODILE, eh?  ..." chain

# After the YES press that opens the keyboard, give the game a beat to
# render the keyboard before type_kiwi() starts pushing the D-pad — the
# first move is otherwise eaten by the transition and the cursor stays
# at (0,0), making the first letter come out wrong.
KEYBOARD_OPEN_SETTLE = 20

# Input timing.
A_HOLD = 3
# Gen-2 menu cursor needs the D-pad held noticeably longer than A —
# 3 frames was unreliable and the cursor stayed at (0,0) on the
# naming screen, producing "AAAA" every attempt.
DPAD_HOLD = 10
PRESS_GAP = 4

# Minimum frames between consecutive presses, even when the dialog
# detector says the coast is clear.  Stops the script from mashing A
# faster than the game can update WRAM (cry animation, party-fill, etc.)
# and prevents the "joy_lock=0 forever, press every 11 frames" failure
# mode observed on Gold US.
MIN_PRESS_INTERVAL = 10

# Extra settle frames after the nickname is confirmed with START.
# Elm's "TOTODILE, eh?" chain takes a moment to begin and the party
# struct (including DVs) is not finalised until then.
POST_NICKNAME_SETTLE = 60

# Max frames to wait for dialog to become input-ready before forcing a press.
DIALOG_WAIT_MAX = 240

# Print a throughput line every N attempts.
THROUGHPUT_INTERVAL = 50

# WRAM bank register (GBC). Bank 1 holds most Gen-2 game state; if a
# read of party_count returns garbage, check whether SVBK matches.
ADDR_SVBK = 0xFF70

# Golden-ratio constant for bit-avalanche mixing of (master, attempt)
# → 64-bit attempt seed.  Adjacent attempt indices produce
# uncorrelated press patterns despite differing in just one bit.
_ATTEMPT_MIX = 0x9E3779B97F4A7C15
SHOULD_EXIT = False


def attempt_rng_for(master_seed: int, attempt: int) -> random.Random:
    """Build the random.Random used to drive mix_rng() for *attempt*.

    Deterministic in (master_seed, attempt); independent across attempts.
    Reproducing a shiny is then a matter of replaying (master_seed,
    attempt) against the same ROM + save state + PyBoy version.
    """
    return random.Random(
        master_seed ^ ((attempt * _ATTEMPT_MIX) & 0xFFFFFFFFFFFFFFFF)
    )


def file_sha1(path: Path) -> str:
    """SHA-1 of *path*'s contents. Used to fingerprint ROM + save state."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_shiny_history() -> list[dict]:
    """Read all entries from SHINY_LOG_PATH. Missing file = []."""
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
    """One-line-per-shiny summary printed at startup / on --stats."""
    if not history:
        print("Shiny history: (none yet)")
        return
    targets = [s for s in history if s.get("target")]
    print(f"Shiny history: {len(history)} total, {len(targets)} matching the current ATK filter")
    by_atk: dict[int, int] = {}
    for s in history:
        by_atk[s.get("atk", -1)] = by_atk.get(s.get("atk", -1), 0) + 1
    atk_summary = ", ".join(f"ATK={a}:{n}" for a, n in sorted(by_atk.items()))
    print(f"  by ATK: {atk_summary}")
    for s in history[-5:]:
        marker = "TARGET" if s.get("target") else "      "
        iso = s.get("iso", "?")
        print(
            f"  {marker}  {iso}  attempt={s.get('attempt'):>6}  "
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
        description="Pokemon Gold shiny-Totodile starter farm.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--master-seed",
        type=lambda s: int(s, 0),
        default=None,
        help="Override the 64-bit master seed (hex with 0x, or decimal). "
             "Combined with --replay-attempt, reproduces a logged shiny.",
    )
    p.add_argument(
        "--replay-attempt",
        type=int,
        default=None,
        help="Run exactly one attempt at this index, save the resulting "
             "PyBoy state to roms/replay_<seed>_a<N>.state, and exit. "
             "Use with --master-seed to reproduce a logged shiny.",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Print cumulative shiny history (from shinies.jsonl) and exit. "
             "Does not launch the emulator.",
    )
    return p.parse_args(argv)


def log_shiny_found(
    *,
    master_seed: int,
    attempt: int,
    dvs,
    target: bool,
    rom_sha1: str,
    state_sha1: str,
    elapsed_s: float,
    run_frames: int,
    extra: dict | None = None,
) -> dict:
    """Append a shiny record to SHINY_LOG_PATH. Returns the entry written."""
    entry = {
        "ts": time.time(),
        "iso": datetime.datetime.now().isoformat(timespec="seconds"),
        "master_seed": f"0x{master_seed:016x}",
        "attempt": attempt,
        "atk": dvs.attack,
        "def": dvs.defense,
        "spd": dvs.speed,
        "spc": dvs.special,
        "raw_dvs": f"0x{dvs.raw:04x}",
        "shiny": True,
        "target": bool(target),
        "min_atk": MIN_ATK_DV,
        "max_atk": MAX_ATK_DV,
        "elapsed_s": round(elapsed_s, 2),
        "run_frames": run_frames,
        "rom_sha1": rom_sha1,
        "state_sha1": state_sha1,
        "reproduce": (
            f"python shiny_starter.py --master-seed 0x{master_seed:016x} "
            f"--replay-attempt {attempt}"
        ),
    }
    if extra:
        entry.update(extra)
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
        print("  2. Walk into Elm's lab and stand facing Totodile's", file=sys.stderr)
        print("     Pokeball, ready to press A.", file=sys.stderr)
        print("  3. In the PyBoy window, Shift+1 to save to slot 1.", file=sys.stderr)
        print("  4. Close the window, then:", file=sys.stderr)
        print(f"     mv roms/pokemon_gold.gbc.state1 {STATE}", file=sys.stderr)
        return 1

    if SPEED not in ("FAST", "SLOW"):
        print(f"ERROR: SPEED must be 'FAST' or 'SLOW', got {SPEED!r}", file=sys.stderr)
        return 1
    slow = SPEED == "SLOW"

    master_seed = (
        args.master_seed if args.master_seed is not None else secrets.randbits(64)
    )
    replay_attempt = args.replay_attempt

    rom_sha1 = file_sha1(ROM)
    state_sha1 = file_sha1(STATE)

    history = load_shiny_history()
    print_shiny_history(history)
    print()
    print(f"MASTER_SEED=0x{master_seed:016x}  (OS-entropy mix_rng; 8-16 presses + 0-511 frame jitter)")
    print(f"ROM sha1={rom_sha1[:12]}…  save_state sha1={state_sha1[:12]}…")
    if replay_attempt is not None:
        print(
            f"REPLAY MODE: running only attempt {replay_attempt} "
            f"with master_seed=0x{master_seed:016x}, then exiting."
        )
    print(
        f"Hunting shiny Totodile with ATK DV in "
        f"[{MIN_ATK_DV}, {MAX_ATK_DV}]  (HEADLESS={HEADLESS}, SPEED={SPEED})"
    )

    pyboy = PyBoy(str(ROM), window="null" if HEADLESS else "SDL2")
    try:
        pyboy.sound_emulated = False
    except AttributeError:
        pass
    # FAST: 0 = unthrottled.  SLOW: 1 = real-time, so you can watch the
    # game and the debug stream side-by-side.
    pyboy.set_emulation_speed(0 if not slow else 1)

    # Per-attempt frame counter, reset each load_state().  Used only to
    # tag debug lines so timing between events is visible.
    frame_count = [0]
    # Cumulative frame counter across all attempts; never reset.  Drives
    # the throughput report.
    total_frames = [0]
    start_time = time.monotonic()

    # Per-DV-slot histograms (16 buckets each) + progressive shiny-
    # precursor counters.  These let us see WHERE the distribution
    # diverges from uniform: e.g. if DEF=10 hits at expected rate but
    # DEF=SPD=10 doesn't, the slots are correlated; if a single bucket
    # is over-/under-represented in any one slot, that slot is biased.
    hist_atk = [0] * 16
    hist_def = [0] * 16
    hist_spd = [0] * 16
    hist_spc = [0] * 16
    count_def10 = 0
    count_def10_spd10 = 0
    count_def10_spd10_spc10 = 0
    count_shiny = 0
    count_target = 0
    # Track DV pairs we've seen so we can detect cycle/repeat patterns
    # (the bug the old `f33c90f` commit hunted).  Bounded so the dict
    # doesn't grow without limit; only matters in the first few thousand
    # attempts where a repeat would be most diagnostic.
    seen_dvs: dict[int, int] = {}
    dup_count = 0
    DUP_TRACK_LIMIT = 10000

    dv_log = open(DV_LOG_PATH, "a", buffering=1)

    # -- low-level helpers --------------------------------------------------

    def tick(n: int = 1) -> None:
        # render=False saves the screen rendering work in headless mode
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

    def dbg(msg: str) -> None:
        if slow:
            print(f"[f={frame_count[0]:>6}] {msg}", flush=True)

    def dump_diagnostic(label: str) -> None:
        """Hex-dump WRAM regions we care about. Always prints (gated by caller)."""
        svbk = read_u8(ADDR_SVBK) & 0x07
        print(f"  ── DUMP: {label} ── (frame={frame_count[0]}, SVBK={svbk})", flush=True)
        print(
            f"  ADDR_PARTY_COUNT @ 0x{ADDR_PARTY_COUNT:04X} = "
            f"0x{read_u8(ADDR_PARTY_COUNT):02X}",
            flush=True,
        )
        # 64 bytes centred a bit before wPartyCount so we see the
        # surrounding state.
        base = ADDR_PARTY_COUNT - 8
        for off in range(0, 64, 16):
            line = " ".join(f"{read_u8(base + off + i):02X}" for i in range(16))
            print(f"  0x{base + off:04X}: {line}", flush=True)
        # First party slot (48 bytes) — should be all-zero until filled.
        print(f"  ── party slot 0 @ 0x{ADDR_PARTY_MON1:04X} ──", flush=True)
        for off in range(0, PARTY_MON_SIZE, 16):
            line = " ".join(
                f"{read_u8(ADDR_PARTY_MON1 + off + i):02X}" for i in range(16)
            )
            print(f"  0x{ADDR_PARTY_MON1 + off:04X}: {line}", flush=True)
        jl = read_u8(ADDR_JOY_LOCK)
        print(
            f"  JOY_LOCK   @ 0x{ADDR_JOY_LOCK:04X} = "
            f"0x{jl:02X} (bit4={bool(jl & 0x10)} "
            f"bit6={bool(jl & 0x40)} bit7={bool(jl & 0x80)})",
            flush=True,
        )
        print(
            f"  TEXT_DELAY @ 0x{ADDR_TEXT_DELAY:04X} = "
            f"0x{read_u8(ADDR_TEXT_DELAY):02X}",
            flush=True,
        )
        print(
            f"  GAME_STATE @ 0x{ADDR_GAME_STATE:04X} = "
            f"0x{read_u8(ADDR_GAME_STATE):02X}",
            flush=True,
        )
        print(
            f"  PARTY_SPECIES @ 0x{ADDR_PARTY_SPECIES:04X} = "
            + " ".join(f"{read_u8(ADDR_PARTY_SPECIES + i):02X}" for i in range(7)),
            flush=True,
        )

    # -- state queries ------------------------------------------------------

    def party_count() -> int:
        return read_u8(ADDR_PARTY_COUNT)

    def dialog_active() -> bool:
        # Mirrors GoldReader.read_dialog(): in Gold, wJoypadDisable
        # (0xD8BA) uses bits 4/6/7 — treat any nonzero byte as "input
        # disabled". Also treat text-delay > 0 as "still animating".
        return read_u8(ADDR_JOY_LOCK) != 0 or read_u8(ADDR_TEXT_DELAY) != 0

    def wait_input_ready(max_frames: int = DIALOG_WAIT_MAX) -> None:
        """Tick until the game is no longer animating text / locked out of input."""
        # Chunks of 4 cut Python-loop overhead vs. tick(1) per frame.
        for _ in range(max_frames // 4):
            if not dialog_active():
                return
            tick(4)
        # If we fell through, dialog stayed "active" the whole window —
        # surface this in SLOW mode because it usually means our
        # detection bits are wrong, not that the game is really busy.
        if slow:
            dbg(
                f"wait_input_ready EXHAUSTED max={max_frames} "
                f"joy=0x{read_u8(ADDR_JOY_LOCK):02X} "
                f"txt=0x{read_u8(ADDR_TEXT_DELAY):02X}"
            )

    def press_a_when_ready() -> None:
        wait_input_ready()
        press("a")
        # Even if the dialog detector said "ready", the game often
        # needs a handful of frames after a press to write its next
        # state (party-fill, text-delay-frames re-arming, joy-lock
        # toggling for the cry animation, ...).  Without this floor the
        # script mashes A at ~11-frame intervals and out-runs the
        # game's bookkeeping.
        tick(MIN_PRESS_INTERVAL)

    def load_state() -> None:
        with open(STATE, "rb") as f:
            pyboy.load_state(f)
        tick(4)

    # -- RNG mixing --------------------------------------------------------

    def mix_rng(attempt: int, rng: random.Random) -> None:
        """Mix Gen-2's RNG by pressing B/SELECT in an entropy-driven
        pattern, then add an idle-tick cycle jitter.

        Each B/SELECT press goes through the joypad handler, which is
        on the Gen-2 input path that reads rDIV and stirs hRandomAdd /
        hRandomSub.  Different press patterns produce different cycle
        deltas → different rDIV reads → different DVs at gen time.

        The press loop alone got us from ~790 effective DV outcomes to
        ~3500.  The trailing idle-tick jitter (0..511 frames) widens
        the cycle-delta range another ~8 bits, which empirically
        pushes effective coverage close to the full 65536 DV space.
        Idle ticks DO matter here because the game's own VBlank handler
        calls Random each frame — those calls stir rDIV into the RNG
        state too.

        *rng* is a random.Random whose seed is derived from
        (master_seed, attempt) — see attempt_rng_for().  This keeps
        each attempt's press pattern independent across attempts AND
        reproducible: same (master_seed, attempt) → same pattern →
        same DVs, given the same ROM + save state + PyBoy version.
        """
        n_presses = rng.randint(8, 16)
        for _ in range(n_presses):
            button = "b" if rng.getrandbits(1) else "select"
            # Widened from the old 3..10 range — more cycle-delta
            # variance per press means richer rDIV coverage.
            gap = rng.randint(3, 30)
            press(button, hold=A_HOLD, gap=gap)
        # Trailing cycle jitter: 0..511 idle frames lets the game's
        # per-VBlank Random() calls accumulate at varying rDIV phases,
        # which empirically breaks past the ~3500 plateau we hit with
        # press-mixing alone.
        tick(rng.randint(0, 511))
        dbg(f"mix_rng attempt={attempt} n_presses={n_presses}")

    # -- DV / nickname readers ---------------------------------------------

    def slot0_species_and_dvs():
        base = ADDR_PARTY_MON1
        species = read_u8(base + PARTYMON_OFF_SPECIES)
        b0 = read_u8(base + PARTYMON_OFF_DVS)
        b1 = read_u8(base + PARTYMON_OFF_DVS + 1)
        return species, decode_dvs(b0, b1)

    def slot0_nickname() -> str:
        chars = []
        for i in range(NAME_SIZE):
            b = read_u8(ADDR_PARTY_NICKS + i)
            if b == 0x50:
                break
            chars.append(GEN2_ENCODING.get(b, "?"))
        return "".join(chars)

    # -- keyboard navigation -----------------------------------------------

    # 9x6 uppercase grid.  Cursor starts at row 0, col 0 = 'A'.
    # Per the task spec:
    #   K -> (1, 1)
    #   I -> (0, 8)
    #   W -> (2, 4)
    #   I -> (0, 8)
    KIWI_KEYS = [
        ("K", 1, 1),
        ("I", 0, 8),
        ("W", 2, 4),
        ("I", 0, 8),
    ]

    # Frames to wait between releasing one D-pad direction and pressing
    # the next.  PRESS_GAP (8) was empirically too tight on the Gen-2
    # naming keyboard.
    DPAD_GAP = 7

    def move_cursor(dr: int, dc: int) -> None:
        for _ in range(dr):
            press("down", hold=DPAD_HOLD, gap=DPAD_GAP)
        for _ in range(-dr):
            press("up", hold=DPAD_HOLD, gap=DPAD_GAP)
        for _ in range(dc):
            press("right", hold=DPAD_HOLD, gap=DPAD_GAP)
        for _ in range(-dc):
            press("left", hold=DPAD_HOLD, gap=DPAD_GAP)

    def type_kiwi() -> None:
        cur_r, cur_c = 0, 0
        for _ch, r, c in KIWI_KEYS:
            move_cursor(r - cur_r, c - cur_c)
            press("a")
            # Give the keyboard a beat to register the letter before
            # the next cursor move.
            tick(MIN_PRESS_INTERVAL)
            cur_r, cur_c = r, c
        # START confirms the name on the Gen-2 naming screen.  Pressing
        # A here would just type a fifth character.
        press("start")
        # The game needs time to dismiss the keyboard, return to the
        # overworld dialog flow, and start writing the final party
        # struct.  Reading DVs immediately gives stale/garbage.
        tick(POST_NICKNAME_SETTLE)

    # -- main loop ----------------------------------------------------------

    # In replay mode, jump the counter to (replay - 1) so the first
    # iteration runs at attempt == replay_attempt.
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
                f"=== attempt {attempt} (SPEED={SPEED}, DUMP_MEMORY={DUMP_MEMORY}, "
                f"HEADLESS={HEADLESS}, master=0x{master_seed:016x}, "
                f"ATK target [{MIN_ATK_DV},{MAX_ATK_DV}]) ==="
            )

            # Per-attempt RNG seeded from (master_seed, attempt) so the
            # press pattern is independent across attempts but fully
            # reproducible given the pair.  See mix_rng() docstring.
            rng = attempt_rng_for(master_seed, attempt)
            mix_rng(attempt, rng)

            # Phase 1: Pokeball interact + "WANT THIS TOTODILE?" YES.
            filled = False
            for i in range(MAX_PRESSES_TO_PARTY_FILL):
                pc = party_count()
                dbg(
                    f"phase1 press={i:>2} party_count=0x{pc:02X} "
                    f"joy=0x{read_u8(ADDR_JOY_LOCK):02X} "
                    f"txt=0x{read_u8(ADDR_TEXT_DELAY):02X}"
                )
                if pc > 0:
                    filled = True
                    break
                # Attempt-derived pre-press wait shifts when our A
                # lands relative to the game's per-frame work, so the
                # RNG sampled at DV-generation time differs even when
                # the press count is identical.
                extra = (attempt * 7 + i * 3) % 5
                if extra:
                    tick(extra)
                press_a_when_ready()
            if not filled:
                print(
                    f"[{attempt}] timed out waiting for party_count > 0",
                    file=sys.stderr,
                )
                if DUMP_MEMORY:
                    dump_diagnostic("phase1 TIMEOUT")
                continue
            if DUMP_MEMORY:
                dump_diagnostic("party_count > 0")

            # Early DV check — party slot 0 (species + DVs) is finalised
            # the instant party_count flips to 1, well before Elm's
            # "received TOTODILE!" dialog finishes.  On a non-shiny we
            # bail here and skip ~2350 frames of dialog/nickname work
            # per attempt.
            species, dvs = slot0_species_and_dvs()
            shiny = is_shiny(dvs)
            atk_ok = MIN_ATK_DV <= dvs.attack <= MAX_ATK_DV
            target = shiny and atk_ok
            species_name = SPECIES_NAMES.get(species, f"???({species})")

            if target:
                status = "*** TARGET SHINY ***"
            elif shiny:
                status = f"*** SHINY (ATK {dvs.attack} outside [{MIN_ATK_DV},{MAX_ATK_DV}]) ***"
            else:
                status = "not shiny"
            print(
                f"[{attempt:>4}] {species_name:>10}  "
                f"ATK={dvs.attack:2d} DEF={dvs.defense:2d} "
                f"SPD={dvs.speed:2d} SPC={dvs.special:2d}  "
                f"{status}"
            )

            # -- distribution + repeat tracking ------------------------
            if species == TOTODILE_ID:
                hist_atk[dvs.attack] += 1
                hist_def[dvs.defense] += 1
                hist_spd[dvs.speed] += 1
                hist_spc[dvs.special] += 1
                if dvs.defense == 10:
                    count_def10 += 1
                    if dvs.speed == 10:
                        count_def10_spd10 += 1
                        if dvs.special == 10:
                            count_def10_spd10_spc10 += 1
                if shiny:
                    count_shiny += 1
                if target:
                    count_target += 1
                if attempt <= DUP_TRACK_LIMIT:
                    key = dvs.raw
                    if key in seen_dvs:
                        dup_count += 1
                    else:
                        seen_dvs[key] = attempt
                # One line-buffered JSONL write — survives a kill -9.
                # master_seed is the same for every line in a run; it
                # bloats the file (~24 B/line × 12 a/s ≈ 1 MB/hour
                # extra) but makes each line self-contained for grep.
                dv_log.write(
                    f'{{"a":{attempt},"sp":{species},'
                    f'"atk":{dvs.attack},"def":{dvs.defense},'
                    f'"spd":{dvs.speed},"spc":{dvs.special},'
                    f'"shiny":{int(shiny)},"target":{int(target)},'
                    f'"master":"0x{master_seed:016x}"}}\n'
                )

            if attempt % THROUGHPUT_INTERVAL == 0:
                elapsed = time.monotonic() - start_time
                rate = attempt / elapsed if elapsed > 0 else 0.0
                avg_frames = total_frames[0] / attempt
                # Per-slot deviation: most-over- and most-under-
                # represented value, with deviation from expected
                # uniform count (attempt/16).
                exp_slot = attempt / 16.0
                def slot_extremes(h: list[int]) -> str:
                    over = max(range(16), key=lambda v: h[v])
                    under = min(range(16), key=lambda v: h[v])
                    return (
                        f"max v={over:2d} n={h[over]:>4} ({(h[over]-exp_slot)/exp_slot:+.1%}), "
                        f"min v={under:2d} n={h[under]:>4} ({(h[under]-exp_slot)/exp_slot:+.1%})"
                    )

                print(
                    f"[{attempt}] rate: {rate:.2f} a/s, {avg_frames:.0f} f/a"
                )
                print(
                    f"  DEF=10: {count_def10:>4} (exp {attempt/16:.1f}), "
                    f"D&S=10: {count_def10_spd10:>3} (exp {attempt/256:.2f}), "
                    f"D&S&P=10: {count_def10_spd10_spc10:>2} (exp {attempt/4096:.3f}), "
                    f"shinies: {count_shiny} (exp {attempt/8192:.2f}), "
                    f"targets: {count_target} (exp {attempt/32768:.3f})"
                )
                print(f"  ATK hist: {slot_extremes(hist_atk)}")
                print(f"  DEF hist: {slot_extremes(hist_def)}")
                print(f"  SPD hist: {slot_extremes(hist_spd)}")
                print(f"  SPC hist: {slot_extremes(hist_spc)}")
                if attempt <= DUP_TRACK_LIMIT:
                    uniq = len(seen_dvs)
                    # Expected duplicates over N draws from 2^16 buckets:
                    # ≈ N(N-1) / (2 * 65536) — birthday paradox arithmetic.
                    exp_dups = attempt * (attempt - 1) / (2 * 65536)
                    print(
                        f"  unique DV combos: {uniq}/{attempt} "
                        f"(dups {dup_count}, exp ~{exp_dups:.1f} for fair RNG over 2^16)"
                    )

            # Log every shiny (target or not) to shinies.jsonl with
            # full (master_seed, attempt) reproduction info.  Non-target
            # shinies happen ~3x as often as target ones; capturing
            # them is valuable for confirming RNG health and tracking
            # the user's empirical shiny rate.
            if shiny and species == TOTODILE_ID:
                shiny_elapsed = time.monotonic() - start_time
                log_shiny_found(
                    master_seed=master_seed,
                    attempt=attempt,
                    dvs=dvs,
                    target=target,
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

            # Replay mode short-circuits the loop: we've done the one
            # attempt the user asked about, captured its state, and
            # printed its DVs.  Skip the dialog/nickname flow entirely.
            if replay_attempt is not None:
                replay_state_path = ROOT / "roms" / (
                    f"replay_{master_seed:016x}_a{attempt}.state"
                )
                with open(replay_state_path, "wb") as f:
                    pyboy.save_state(f)
                print(
                    f"REPLAY DONE: attempt={attempt} "
                    f"ATK={dvs.attack} DEF={dvs.defense} "
                    f"SPD={dvs.speed} SPC={dvs.special} "
                    f"{'shiny' if shiny else 'not shiny'}"
                    f"{' (target)' if target else ''}"
                )
                print(f"REPLAY DONE: state saved to {replay_state_path}")
                break

            if species != TOTODILE_ID:
                print(
                    f"  └─ wrong species; expected Totodile ({TOTODILE_ID})",
                    file=sys.stderr,
                )
                continue

            if not target:
                continue

            # ── Shiny found — finish the dialog so the saved state is
            # in a clean, post-nickname overworld position. ──────────

            # Phase 2: advance past the cry / "received TOTODILE" text
            # and Elm flavor lines, then press YES on the nickname Y/N
            # menu so the keyboard opens.  Exactly PRESSES_PARTY_TO_KEYBOARD
            # presses — see that constant's comment for why over-pressing
            # here is what was causing "AAAAKIWI".
            for i in range(PRESSES_PARTY_TO_KEYBOARD):
                dbg(
                    f"phase2 press={i:>2} "
                    f"joy=0x{read_u8(ADDR_JOY_LOCK):02X} "
                    f"txt=0x{read_u8(ADDR_TEXT_DELAY):02X}"
                )
                press_a_when_ready()
            # The final press above is the YES on the Y/N menu, which
            # opens the keyboard.  Give it time to fully render before
            # type_kiwi() starts mashing the D-pad.
            tick(KEYBOARD_OPEN_SETTLE)

            # Phase 3: type KIWI and press START to confirm.
            dbg("phase3 type_kiwi")
            type_kiwi()

            # Phase 4: clear Elm's "TOTODILE, eh?" follow-up dialog.
            for i in range(PRESSES_POST_NICKNAME):
                if slow and i % 10 == 0:
                    dbg(
                        f"phase4 press={i:>2} "
                        f"joy=0x{read_u8(ADDR_JOY_LOCK):02X} "
                        f"txt=0x{read_u8(ADDR_TEXT_DELAY):02X}"
                    )
                press_a_when_ready()

            nick = slot0_nickname()

            elapsed = time.monotonic() - start_time
            avg_rate = attempt / elapsed if elapsed > 0 else 0.0

            print()
            print("=" * 60)
            print(f"  ✨  SHINY TOTODILE  ✨   on attempt {attempt}")
            print(
                f"  DVs:  ATK={dvs.attack}  DEF={dvs.defense}  "
                f"SPD={dvs.speed}  SPC={dvs.special}"
            )
            print(f"  Nickname: {nick!r}")
            print(f"  Total attempts: {attempt}")
            print(f"  Total elapsed:  {elapsed:.1f}s")
            print(f"  Avg rate:       {avg_rate:.2f} attempts/sec")
            print("=" * 60)
            print()

            with open(SHINY_STATE, "wb") as f:
                pyboy.save_state(f)
            print(f"Saved shiny state to {SHINY_STATE}")
            if HEADLESS:
                print(
                    "HEADLESS run — no window to admire.  To view your shiny:"
                )
                print(f"  cp {SHINY_STATE} {STATE.with_suffix('.state1')}")
                print("  python play.py   # then Shift+L (or your load key) to load slot 1")
            else:
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
