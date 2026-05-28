# Pokémon Gold/Silver RNG Manipulation — Reference Guide

A practical guide to how Gen-2 Pokémon Gold/Silver generates random numbers,
how DVs are rolled for starters/wild encounters, and how to manipulate them
deterministically via direct HRAM writes against a PyBoy save state.

## TL;DR

- The 8-bit `hRandomSub` byte is the **return value** of every `Random()` call.
- Writing to `hRandomSub` right before DV generation **deterministically
  controls the high byte of the DVs**.
- `hRandomAdd` is secondary — it only flips the carry flag that propagates
  into the next Random call. Single-bit LSB effect.
- The two DV bytes (`DV0 = ATK:DEF`, `DV1 = SPD:SPC`) are linked by a fixed
  delta per save state. To reach an *arbitrary* DV pair you need to try
  multiple PRE_DV save states at different frame offsets to find one with
  the desired delta.

## Memory addresses

| ROM             | hRandomAdd | hRandomSub |
| --------------- | ---------- | ---------- |
| **Gold/Silver** | `0xFFE3`   | `0xFFE4`   |
| Crystal         | `0xFFE1`   | `0xFFE2`   |
| `rDIV` (CPU)    | `0xFF04`   |            |

The earlier commits in this repo (`91e99c5`, `24115e1`) used `0xFFD9` /
`0xFFDA`. **Both addresses were wrong** — that's why those attempts saw
DVs cycle through a tiny subspace and gave up. Always cross-reference
against the [pret/pokegold](https://github.com/pret/pokegold)
disassembly when verifying HRAM offsets.

## The Random() routine

From `pret/pokegold/home/random.asm` (Gold/Silver):

```asm
Random::
    push bc
    ldh a, [rDIV]       ; A = current rDIV value
    ld b, a
    ldh a, [hRandomAdd]
    adc b               ; hRandomAdd_new = hRandomAdd + rDIV + carry_in
    ldh [hRandomAdd], a
    ldh a, [rDIV]       ; A = rDIV (may differ from first read by a few cycles)
    ld b, a
    ldh a, [hRandomSub]
    sbc b               ; hRandomSub_new = hRandomSub - rDIV - carry_from_adc
    ldh [hRandomSub], a ; …and this is the returned random byte
    pop bc
    ret
```

Key observations:

1. **`Random()` returns `hRandomSub_new` in register A.** Callers that use
   the return value (e.g. DV generation) read this byte directly.
2. **`rDIV` is the GB hardware divider register** — increments at 16384 Hz
   independent of CPU stalls. PyBoy's `save_state` captures it; `load_state`
   restores it. So `rDIV` at a given point is deterministic for a fixed
   save state.
3. **`Random()` is also called from the VBlank handler** every frame for
   graphics/cosmetic RNG, which stirs `hRandomAdd` / `hRandomSub` even when
   you're not touching the game.

## DV generation timing

Per the [TASvideos Gen-2 RNG reference](https://tasvideos.org/GameResources/GB/PokemonGen2):

- **Starter DVs** are rolled when the *"(player) received POKEMON!"*
  textbox is **closed** (the A press *after* the YES press on the Y/N
  menu, *not* the YES press itself).
- **Wild Pokémon DVs** are rolled at the moment of encounter (when
  `wBattleMode` transitions to 1).

The starter give routine calls `Random()` twice in immediate succession:

1. **First call** → returned byte becomes `wPartyMon1DVs+0` (ATK in high
   nibble, DEF in low nibble).
2. **Second call** → returned byte becomes `wPartyMon1DVs+1` (SPD in high
   nibble, SPC in low nibble).

Other `Random()` calls run before/between/after these for unrelated game
logic. The byte we write to `hRandomSub` must survive into the first DV
call — that means **we need a save state captured very close to the moment
of the DV-gen calls.**

## Shiny criterion (Gen 2)

A Pokémon is shiny iff its DVs satisfy:

```
ATK ∈ {2, 3, 6, 7, 10, 11, 14, 15}      (i.e. low 2 bits of ATK are 10 or 11 binary)
DEF = SPD = SPC = 10
```

In raw bytes this means `DV0 = X*16 + 10` for some shiny ATK X, and
`DV1 = 0xAA` exactly. The most desirable shiny is **ATK=15 → DV0=0xFA,
DV1=0xAA** because base stats are best at max ATK.

## Empirical: what writing to each HRAM byte actually does

Tested against `roms/pokemon_gold.gbc.pre_dv.state` (one frame before DV
gen) by sweeping each address across all 16 representative values:

| Write target | Distinct DV outcomes | Effect on DV gen                           |
| ------------ | -------------------: | ------------------------------------------ |
| `0xFFE3` (hRandomAdd) | 3       | Only flips carry into the sbc — ±1 LSB.    |
| `0xFFE4` (hRandomSub) | 16 / 16 | **Full control of DV high byte.**          |
| any other HRAM        | 1       | No effect (or game crashes / wrong species).|

A full 256-value sweep of `hRandomSub` produced **256 unique DV pairs**
— a clean bijection. All 16 ATK values are reachable.

## The fixed-delta problem (and why one save state isn't enough)

The second `Random()` call inside DV gen runs ~9 CPU cycles after the
first. In that interval `rDIV` advances by some small fixed amount that
depends on the save state's exact phase. The result:

```
DV1 = (DV0 - delta_rDIV - carry') mod 256
```

So **`delta = (DV1 - DV0) mod 256` is constant within a save state.**

Empirical delta from `pre_dv.state` we built: **`0x67`** for all
256 values of `hRandomSub` written.

Target deltas for shiny outcomes:

| Target shiny | DV0   | DV1   | required delta |
| ------------ | ----- | ----- | -------------- |
| ATK=15       | 0xFA  | 0xAA  | `0xB0`         |
| ATK=14       | 0xEA  | 0xAA  | `0xC0`         |
| ATK=11       | 0xBA  | 0xAA  | `0xF0`         |
| ATK=10       | 0xAA  | 0xAA  | `0x00`         |
| ATK=7        | 0x7A  | 0xAA  | `0x30`         |
| ATK=6        | 0x6A  | 0xAA  | `0x40`         |
| ATK=3        | 0x3A  | 0xAA  | `0x70`         |
| ATK=2        | 0x2A  | 0xAA  | `0x80`         |

A save state with delta `0x67` will never produce a shiny — none of the
target deltas line up.

### Changing the delta

To get a different delta, you have to capture the PRE_DV save state at a
different `rDIV` phase. Practically:

1. Build a PRE_DV state at frame F (as our `--build-state` flow does).
2. If its delta isn't useful, advance the calibration by 1 frame and
   recapture. Each frame shifts `rDIV` by ~273 ticks (`16384/60`), so
   the delta wraps through its full range over ~256 different
   single-frame save points.
3. Sweep `hRandomSub` against the new state to confirm the new delta and
   check shiny reachability.

A full manipulation rig would automatically iterate F across a search
space until it finds a state with the desired target's delta, then sweep
`hRandomSub` once to find the magic byte.

## Step-by-step manipulation workflow (Gold US, our setup)

This is what `shiny_starter_manip.py` aims to do:

1. **Build YN_state** — from `roms/pokemon_gold.gbc.state` (pre-Pokeball),
   mash A presses, snapshotting state in memory before each press. The
   press that flips `party_count: 0 → 1` is the *"received Pokémon"
   textbox close press*. The snapshot just before it is the Y/N-menu
   state. (Note: in earlier docs we called this YN_state, but it's
   actually the "received" textbox state — the *real* Y/N menu state is
   one press earlier. For manipulation purposes either works since DV
   gen happens on the close press.)

2. **Build PRE_DV_state** — from YN_state, press A and tick
   frame-by-frame, snapshotting each frame. The frame whose tick first
   flips `party_count` is the DV-gen frame; the snapshot taken just
   *before* that tick is the PRE_DV state. The very next tick after
   loading this state generates DVs.

3. **Probe** — `python shiny_starter_manip.py --probe 0xAA 0xBB`:
   - load PRE_DV state
   - write `pyboy.memory[0xFFE3] = 0xAA; pyboy.memory[0xFFE4] = 0xBB`
   - tick ~16 frames (until `party_count == 1` plus a settle window so
     the engine has time to copy DV bytes from `hRandomSub` into the
     party slot — empirically ~8 extra ticks)
   - read `wPartyMon1DVs` (bytes at `0xDA2A + 0x15`)

4. **Sweep** — full sweep of `hRandomSub` from 0..255. For our test
   state with delta 0x67, no shiny appeared. Need to advance the PRE_DV
   build by some frames and re-sweep.

5. **Goal state** — once you find a `(PRE_DV_state, hRandomSub_write)`
   that produces the target DV pair, you have *instant* repeatable
   target shinies: load + write + tick = DONE. No more brute force.

## Why this is better than brute-force B/SELECT mixing

The brute-force approach (current `shiny_starter.py`) explores the DV
space via Gen-2's normal RNG path — pressing B/SELECT in randomized
patterns + idle ticks to vary `rDIV` phase, then running the full
starter dialog. It works but:

- **Non-deterministic.** Each "shiny" is found at a unique random seed
  state; can't replay it later without recording the exact press sequence.
- **Birthday-paradox waste.** With effective coverage ≈ true 16-bit DV
  space, you need ~65k attempts mean wait for a specific 1-in-65k target.
- **Shiny ATK distribution may be biased.** We observed shiny ATK=15
  may be in a hard-to-reach corner — 12 shinies seen with 0 ATK=15s.

The manipulation approach:

- **Fully deterministic.** Given `(PRE_DV_state, hRandomSub)`, you get
  the same DVs every time. Reproduction is one line of code.
- **Guaranteed coverage** within a PRE_DV state's reachable DV subset.
- **Linear search** through hRandomSub (256 outcomes) or through PRE_DV
  frame offsets (≤256 deltas) — bounded, exhaustive.
- **Pre-computed table.** Build the full lookup once, then any future
  hunt for *any* target DV is an O(1) lookup.

## References

- [pret/pokegold disassembly](https://github.com/pret/pokegold) — source of
  truth for Gen-2 game code. See `home/random.asm` and `ram/hram.asm`.
- [TASvideos: Pokémon Gen 2 RNG](https://tasvideos.org/GameResources/GB/PokemonGen2)
  — concise reference for HRAM addresses, RNG mechanics, and luck-manipulation
  techniques used in tool-assisted speedruns.
- [pokegold/home/random.asm](https://github.com/pret/pokegold/blob/master/home/random.asm)
  — the actual `Random()` subroutine.
- [pokegold/ram/hram.asm](https://github.com/pret/pokegold/blob/master/ram/hram.asm)
  — full HRAM layout including `hRandomAdd` / `hRandomSub`.

## Project file map

| File                         | Purpose                                                       |
| ---------------------------- | ------------------------------------------------------------- |
| `shiny_starter.py`           | Brute-force shiny farm (working baseline).                    |
| `shiny_starter_manip.py`     | HRAM-write manipulation (work-in-progress).                   |
| `shiny_grass.py`             | Wild-encounter shiny farm.                                    |
| `roms/pokemon_gold.gbc.state` | Pre-Pokeball save state.                                     |
| `roms/pokemon_gold.gbc.pre_dv.state` | Auto-built calibration state (1 frame before DV gen). |
| `shinies.jsonl` / `grass_shinies.jsonl` / `manip_shinies.jsonl` | Append-only logs of every shiny found, with reproducer commands. |
