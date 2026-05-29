"""Gen 3 (FireRed/LeafGreen) RNG mechanics — reverse-engineering notes + tools.

This module documents how Pokémon FireRed/LeafGreen drives its RNG and how
wild encounters are generated, based on empirical reverse-engineering against
mGBA + the LeafGreen (USA) ROM, cross-checked with community references
(TASvideos Gen-3 RNG, pokemonrng.com, Smogon RNG-Reporter threads, PokeFinder
"Method H").  It is meant to be a living reference: add findings here as we
learn them.

The low-level LCG primitives (``lcg_next`` / ``lcg_prev`` / ``rewind`` /
``gen_method1``) live in :mod:`pokemon_agent.shiny_gen3`; this module builds
the *wild-encounter* layer on top and records the timing facts that decide
what can and can't be manipulated offline.

================================================================================
1. The core RNG
================================================================================
A 32-bit LCG:  ``seed = seed * 0x41C64E6D + 0x6073  (mod 2^32)``.
Each ``Random()`` call advances the seed once and returns the **high 16 bits**
of the new seed.  The live seed lives at ``gRngValue`` — for LeafGreen (USA)
that is **0x03005000** in IWRAM.  It is fully captured by save states, and we
can overwrite it directly to choose the RNG outcome.

================================================================================
2. Overworld per-frame RNG consumption  (MEASURED — seed-independent)
================================================================================
While standing/walking/jiggling in the overworld the game advances the RNG a
**fixed, seed-independent** number of times per frame: empirically **2 calls
per frame**, plus a periodic extra **+1 roughly every 9 frames** (a cosmetic
animation cadence).  This was verified identical across many seeds — see
``MEASURED_OVERWORLD_PROFILE``.

Consequence: the RNG state at any overworld frame F is a *deterministic*
function of the starting seed (advance the LCG by the cumulative call count to
F).  So the *walking* portion of an encounter hunt IS analytically modelable.

================================================================================
3. Encounters are step/turn-gated; "jiggling" works
================================================================================
The wild-encounter check fires when the player completes a step **or a turn**.
You do NOT have to move tiles: tapping opposing directions in place ("jiggle")
turns the character and runs the check every ~3 frames (hold 2 / release 1),
far more often than a full ~22-frame walk step.  Verified: jiggling triggers
valid encounters at ~100% per trial and ~7x more encounters/sec than walking.
(This is exploited by :mod:`shiny_grass_leafgreen`.)

================================================================================
4. THE BARRIER: the battle-init RNG burst is seed-dependent
================================================================================
When the encounter check passes, the *single* frame that starts the battle
consumes a large, **seed-dependent** burst of RNG calls before the Pokémon's
PID/IVs are generated.  Measured: for seeds that trigger on the *same* frame
with *identical* pre-trigger RNG, the PID still landed at burst offsets of
**12, 44, 70, 100** calls (same species, different offsets) — i.e. the battle-
start code contains an RNG-driven loop/branch we have not decoded.

Why this matters: it means we **cannot** (yet) predict the wild PID/IVs
analytically from the *pre-encounter* (walking) seed, because the number of
RNG advances between "seed we wrote" and "PID generation" varies with the seed
in a way that needs the battle-init code (pokefirered disassembly) to model.
This is the difference from the *starter*, where the dialog timing was input-
driven and the offset was a fixed constant (N=90) — fully solvable offline.

How the community sidesteps it: **Sweet Scent**.  Using Sweet Scent forces the
encounter at a controlled point so the generation happens at a *fixed advance*
from a known seed (no walking/transition burst), making it analytically
solvable exactly like the starter.  Tools (PokeFinder/RNG Reporter) work from
the boot seed + a counted "advance" and assume the clean generation sequence
below.  Until we either (a) decode the battle-init burst or (b) use Sweet
Scent, wild hunts here use the deterministic *emulation search* in
:mod:`shiny_grass_leafgreen` instead of an offline one-shot.

================================================================================
5. Wild generation order ("Method H")  — the clean part
================================================================================
Given the seed *at the moment generation starts* (call it the generation
seed), the wild Pokémon is built by consecutive ``Random()`` calls:

    1. slot     = Random() >> 16, then  % 100  -> encounter-slot index (species)
    2. level    = Random() >> 16, then  % (max-min+1) + min   (per-slot range)
    3. PID_low  = Random() >> 16
    4. PID_high = Random() >> 16        ->  PID = (PID_high << 16) | PID_low
    5. IV_word1 = Random() >> 16  (low 15 bits) -> HP, Atk, Def
    6. IV_word2 = Random() >> 16  (low 15 bits) -> Spe, SpA, SpD

This is Method H-1 (no VBlank interruption).  A VBlank firing mid-generation
can insert ONE extra advance between halves, giving H-2 (gap before IVs) or
H-4 (gap between the two IV words) — handle by trying the small gap variants.
Shininess/nature/ability derive from the PID exactly as in
:mod:`pokemon_agent.shiny_gen3` (PID-based; IVs are independent of shininess,
so for a fixed TID/SID shiny+flawless is impossible — same coupling cap as the
starter).

Synchronize and Cute Charm leads do **not** affect FR/LG wild PIDs, so nature
cannot be forced via a lead — only by seed choice.

================================================================================
6. Reverse lookup ("give me the seed for THIS outcome")
================================================================================
Forward sim (seed -> outcome) and reverse lookup (outcome -> seed) are the same
problem: enumerate seeds through the forward function and keep those whose
outcome matches the target — that *is* the offline search.  For fixed-offset
cases you can also invert directly: find the generation seed G that produces
the target, then ``rewind(G, offset)`` gives the value to write `offset` calls
earlier.  This is exactly what the starter hunt does
(:mod:`shiny_leafgreen_starter`).  It works for wild too **once** the
generation seed is reachable at a fixed offset (Sweet Scent), but is blocked
for walking encounters by the §4 burst.
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.shiny_gen3 import Gen3IVs, lcg_next, rewind  # noqa: F401  (re-export)

U16 = 0xFFFF

# Empirical overworld per-frame RNG-call profile (LeafGreen, in grass, jiggling).
# Seed-independent.  Index = frame; value = Random() calls that frame.
# Documented as data so it can be re-checked / re-measured per location.
MEASURED_OVERWORLD_PROFILE = "≈2 calls/frame, +1 every ~9 frames (cosmetic)"

# Standard Gen-3 land encounter-slot cumulative thresholds (percent).
# slot i is chosen when (Random()>>16) % 100 < SLOT_CUMULATIVE[i] (first match).
# Slot probabilities: 20,20,10,10,10,10,5,5,4,4,1,1.
SLOT_CUMULATIVE = (20, 40, 50, 60, 70, 80, 85, 90, 94, 98, 99, 100)


def slot_index(rand16: int) -> int:
    """Map a Random()>>16 value to a land encounter-slot index (0..11)."""
    r = rand16 % 100
    for i, thr in enumerate(SLOT_CUMULATIVE):
        if r < thr:
            return i
    return 11


@dataclass(frozen=True)
class WildSpawn:
    """A fully-decoded wild generation result (Method H-1) from a gen seed."""
    slot: int
    level_rand: int
    pid: int
    ivs: Gen3IVs

    @property
    def nature(self) -> int:
        return self.pid % 25


def generate_wild(gen_seed: int, iv_gap: int = 0) -> WildSpawn:
    """Run Method-H wild generation from ``gen_seed`` (the seed state *before*
    the slot ``Random()`` call).

    ``iv_gap`` models the VBlank wrinkle: 0 = H-1 (IVs immediately after PID),
    1 = one extra advance before the IV words (H-2-ish).  Returns the encounter
    slot index, the raw level roll, the PID, and the IVs.  Map ``slot`` to a
    species and ``level_rand`` to a concrete level using the area's encounter
    table (see :func:`level_from_rand`).
    """
    s = lcg_next(gen_seed); slot = slot_index(s >> 16)
    s = lcg_next(s); level_rand = (s >> 16) & U16
    s = lcg_next(s); pid_low = (s >> 16) & U16
    s = lcg_next(s); pid_high = (s >> 16) & U16
    pid = ((pid_high << 16) | pid_low) & 0xFFFFFFFF
    for _ in range(iv_gap):
        s = lcg_next(s)
    s = lcg_next(s); iv1 = (s >> 16) & 0x7FFF
    s = lcg_next(s); iv2 = (s >> 16) & 0x7FFF
    ivs = Gen3IVs(
        hp=iv1 & 31, attack=(iv1 >> 5) & 31, defense=(iv1 >> 10) & 31,
        speed=iv2 & 31, sp_attack=(iv2 >> 5) & 31, sp_defense=(iv2 >> 10) & 31,
    )
    return WildSpawn(slot=slot, level_rand=level_rand, pid=pid, ivs=ivs)


def level_from_rand(level_rand: int, min_level: int, max_level: int) -> int:
    """Concrete level from the raw level roll and the slot's level range."""
    span = max_level - min_level + 1
    return min_level + (level_rand % span)
