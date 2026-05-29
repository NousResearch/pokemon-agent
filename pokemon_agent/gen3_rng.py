"""Gen 3 (FireRed/LeafGreen) RNG mechanics — reverse-engineering notes + tools.

Documents how Pokémon FireRed/LeafGreen drives its RNG and generates wild
encounters, reverse-engineered against mGBA + the LeafGreen (USA) ROM and
cross-checked with the pret/pokefirered disassembly (which covers FR *and* LG)
plus community references (TASvideos Gen-3 RNG, pokemonrng.com, PokeFinder
"Method H").  Living reference — add findings here as we learn them.

Low-level LCG primitives (``lcg_next``/``lcg_prev``/``rewind``/``gen_method1``)
live in :mod:`pokemon_agent.shiny_gen3`; this module adds the wild-encounter
layer and records the timing facts that decide what's manipulable offline.

================================================================================
1. The core RNG
================================================================================
LCG: ``seed = seed * 0x41C64E6D + 0x6073 (mod 2^32)``.  Each ``Random()`` call
advances the seed once and returns the **high 16 bits**.  ``Random32()`` =
``Random() | (Random() << 16)`` (two calls; first = low half, second = high
half).  The live seed ``gRngValue`` is at **0x03005000** (LeafGreen USA) in
IWRAM — captured by save states and directly overwritable.

================================================================================
2. Overworld per-frame RNG consumption  (MEASURED — seed-independent)
================================================================================
Standing/walking/jiggling, the game advances the RNG a **fixed, seed-
independent** number of times per frame: ~**2 calls/frame**, plus a periodic
**+1 every ~9 frames** (cosmetic).  Verified identical across many seeds.  So
the RNG state at any overworld frame is a deterministic function of the start
seed — the *walking* phase is analytically modelable.

================================================================================
3. Encounters are step/turn-gated; "jiggling" works
================================================================================
The encounter check fires on a completed step **or turn** — you needn't change
tiles.  Tapping opposing directions in place ("jiggle", hold 2 / release 1)
runs the check every ~3 frames, ~7x more encounters/sec than walking whole
tiles, at ~100% trigger.  Exploited by :mod:`shiny_grass_leafgreen`.

================================================================================
4. Wild generation sequence — DECODED (pret/pokefirered)
================================================================================
From ``src/wild_encounter.c`` ``GenerateWildMon`` + ``src/pokemon.c``
``CreateMonWithNature`` / ``CreateBoxMon``, the calls when an encounter fires:

    rate  : WildEncounterRandom() % 2880 < area_rate     (gates the encounter)
    slot  : Random() % ENCOUNTER_CHANCE_LAND_MONS_TOTAL   -> species (thresholds)
    level : Random() % (max-min+1) + min
    nature: Random() % 25
    PID   : do { pid = Random32(); } while (pid % 25 != nature)   # NATURE-LOCK LOOP
    IVs   : iv1 = Random();  iv2 = Random()                       # 15 bits each

The **nature-lock loop** is the key FR/LG quirk: a nature is rolled, then the
32-bit PID is **re-rolled until ``pid % 25 == nature``** — a Geometric(~1/25)
loop, ~50 ``Random()`` calls on average (we measured 12-100), 2 calls/iter.
This is the seed-dependent "burst" between the encounter trigger and the PID;
it is fully deterministic and simulable (see :func:`generate_wild`).  Validated
against live encounters: e.g. one Rattata took 48 loop iterations and the
predicted PID + IVs matched exactly.

Shininess/nature/ability derive from the PID as in :mod:`shiny_gen3`.  IVs are
independent of shininess, so for a fixed TID/SID shiny+flawless is impossible
(same coupling cap as the starter).  Synchronize/Cute-Charm leads do NOT affect
FR/LG wild PIDs — nature is only manipulable by seed choice.

================================================================================
5. Generation is CLEAN and offline-predictable (verified by instrumentation)
================================================================================
Single-stepping the generation frame and logging every ``Random()`` call's
return + VCOUNT shows the sequence is exactly §4, call-for-call, with NO extra
mid-generation advance for normal loops.  Example (seed 0x11111111, Rattata):

    idx2 = slot  (->slot 0)   idx3 = level   idx4 = nature (246E % 25 = 1)
    idx5..10 = failed nature-loop pairs       idx11,12 = matching PID (0xD7FA8F35)
    idx13 = IV1 (immediately after PID)        idx14 = IV2

The whole generation runs in the visible region (VCOUNT ~16-66) and finishes
long before VBlank (VCOUNT 160), so no VBlank fires *during* it.  The per-frame
ambient calls (§2) sit at the frame's *start* (VCOUNT ~198), i.e. before the
generation, and are already part of the walk model — not a mid-gen insert.
``generate_wild()`` reproduces real encounters call-for-call given the correct
generation seed (the RNG state right before the slot call).

(Earlier notes here claimed a cycle-dependent "VBlank insertion barrier"; that
was WRONG — an artifact of two buggy probes, a mis-located generation seed and
an input-misaligned re-step.  Determinism was never in question; the generation
is genuinely clean and computable offline.)

Caveat: a *very* long nature-loop (hundreds of iterations) could push the
generation past VCOUNT 160 and take one real VBlank advance mid-stream (the
classic Method H-2/H-4) — rare, and detectable by checking whether the gen
window crosses scanline 160.

================================================================================
5b. Status of the offline model (measured against the emulator)
================================================================================
The gRngValue chain is a perfectly CLEAN LCG from the written seed — verified:
``advance(written_seed, total_calls) == gRngValue`` exactly, zero reseeds.  So
the whole encounter is a pure function of the written seed.

VALIDATED (30/30 random encounters): given the trigger offset N, the generation
seed is ``advance(written_seed, N + 2)`` (the +2 = the burst frame's leading
ambient calls), and :func:`generate_wild` predicts **PID / nature / species /
slot exactly, 100% of the time** (shiny + nature + species are fully solvable
offline).

PARTIALLY predictable: the **IVs**.  One VBlank may insert between the PID and
the IV reads (the gap), and for longer nature-loops the gap can be >1, so
gap∈{0,1} only nails the IVs ~20% of the time.  Workflow: filter offline on the
exact PID criteria (shiny + Mankey + nature), then read the actual IVs from a
quick emulator verification of the handful of survivors.

Trigger offset N (which turn fires) clusters at WILD_TRIGGER_OFFSETS
(256/274/292 here), gated by the per-turn rate check + the separate
WildEncounterRandom RNG; predicting it exactly per seed would need that two-RNG
model, but for searching we just try the few offsets and verify.  Reverse
lookup: pick a target PID, find a generation seed G that makes it, then
``rewind(G, N+2)`` is the value to write (verify in-emulator).

================================================================================
6. Reverse lookup ("seed for THIS outcome")
================================================================================
Forward sim and reverse lookup are the same: enumerate seeds through the
forward function and keep matches (that *is* the offline search).  For fixed-
offset cases, construct the generation seed G that yields the target and
``rewind(G, offset)`` gives the value to write earlier — the starter recipe
(:mod:`shiny_leafgreen_starter`).  Works for wild too once G is reachable at a
fixed offset (Sweet Scent); blocked for walking by §5.
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.shiny_gen3 import Gen3IVs, lcg_next, rewind  # noqa: F401 (re-export)

U16 = 0xFFFF
NUM_NATURES = 25

# Empirical overworld per-frame RNG-call profile (LeafGreen, grass, jiggling).
# Seed-independent.  Documented as prose so it can be re-measured per location.
MEASURED_OVERWORLD_PROFILE = "≈2 calls/frame, +1 every ~9 frames (cosmetic)"

# Standard Gen-3 land encounter-slot cumulative thresholds (percent): slot i is
# chosen when (Random()>>16) % 100 < SLOT_CUMULATIVE[i] (first match).
# Per-slot probabilities: 20,20,10,10,10,10,5,5,4,4,1,1.
SLOT_CUMULATIVE = (20, 40, 50, 60, 70, 80, 85, 90, 94, 98, 99, 100)


def slot_index(rand16: int) -> int:
    """Map a Random()>>16 value to a land encounter-slot index (0..11)."""
    r = rand16 % 100
    for i, thr in enumerate(SLOT_CUMULATIVE):
        if r < thr:
            return i
    return 11


def nature_of(pid: int) -> int:
    return pid % NUM_NATURES


def level_from_rand(level_rand: int, min_level: int, max_level: int) -> int:
    """Concrete level from the raw level roll and the slot's level range."""
    return min_level + (level_rand % (max_level - min_level + 1))


@dataclass(frozen=True)
class WildSpawn:
    """Decoded wild generation result from a generation seed (no-vblank / H-1)."""
    slot: int
    level_rand: int
    nature: int
    pid: int
    ivs: Gen3IVs
    loop_iters: int   # nature-lock iterations (RNG burst length = 2*loop_iters)


def generate_wild(gen_seed: int, iv_gap: int = 0, max_loop: int = 1000) -> WildSpawn:
    """Simulate FR/LG wild generation from ``gen_seed`` — the seed state right
    *before* the slot ``Random()`` call.

    Mirrors ``GenerateWildMon`` -> ``CreateMonWithNature`` exactly: slot, level,
    nature, the nature-lock PID loop, then two IV words.  ``iv_gap`` models the
    single VBlank advance that may land between the PID and the IV reads
    (0 = H-1, no vblank; 1 = H-2).  The slot/level/nature/PID are *before* the
    gap, so they're identical regardless — only the IVs depend on ``iv_gap``.
    Validated against the emulator: e.g. seed 0x00000000 reproduces at
    gen-seed = advance(seed, 294), iv_gap=1.
    """
    s = lcg_next(gen_seed); slot = slot_index(s >> 16)
    s = lcg_next(s); level_rand = (s >> 16) & U16
    s = lcg_next(s); nature = (s >> 16) % NUM_NATURES
    pid = 0
    iters = 0
    for iters in range(1, max_loop + 1):
        s = lcg_next(s); lo = (s >> 16) & U16
        s = lcg_next(s); hi = (s >> 16) & U16
        pid = ((hi << 16) | lo) & 0xFFFFFFFF
        if pid % NUM_NATURES == nature:
            break
    for _ in range(iv_gap):
        s = lcg_next(s)
    s = lcg_next(s); iv1 = (s >> 16) & 0x7FFF
    s = lcg_next(s); iv2 = (s >> 16) & 0x7FFF
    ivs = Gen3IVs(
        hp=iv1 & 31, attack=(iv1 >> 5) & 31, defense=(iv1 >> 10) & 31,
        speed=iv2 & 31, sp_attack=(iv2 >> 5) & 31, sp_defense=(iv2 >> 10) & 31,
    )
    return WildSpawn(slot=slot, level_rand=level_rand, nature=nature,
                     pid=pid, ivs=ivs, loop_iters=iters)


# Trigger-offset constants (LeafGreen, this grass state, jiggle input): the
# encounter generation begins at advance(written_seed, N+2) where the +2 is the
# burst frame's leading ambient calls, and N (calls before the burst frame)
# clusters at these few values (gated by the per-turn rate check + a separate
# WildEncounterRandom RNG).  See §5b.
WILD_TRIGGER_OFFSETS = (256, 274, 292)
WILD_GEN_DELTA = 2  # ambient calls in the burst frame before the slot roll


def predict_wild(written_seed: int, trigger_offset: int):
    """Offline prediction of the encounter for ``written_seed`` (the value put
    into gRngValue) given the trigger offset N (one of WILD_TRIGGER_OFFSETS).

    Returns (h1, h2): the two candidate :class:`WildSpawn` results for the
    no-vblank and one-vblank IV alignments.  PID/nature/slot are identical in
    both; only IVs differ.  Verify against the emulator to resolve which.
    """
    gen_seed = written_seed
    for _ in range(trigger_offset + WILD_GEN_DELTA):
        gen_seed = lcg_next(gen_seed)
    return generate_wild(gen_seed, 0), generate_wild(gen_seed, 1)
