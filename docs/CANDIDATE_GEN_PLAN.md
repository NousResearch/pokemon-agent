# Candidate-Generation Improvement Plan (LeafGreen wild shiny hunts)

**Status:** in progress · **Owner:** Keaton + Claude · **Started:** 2026-05-30

Working document **and** task list. Check items off as we go; append findings to
the Decisions/Findings log at the bottom.

---

## Goal

Get **more and better** shiny wild candidates (esp. for rare slots like
Nidoran♂, 1%), by **widening the reachable IV space**, and — stretch — do the
whole process **faster**.

## Key insight (why this is possible)

An encounter outcome = deterministic function of **(save state S, written seed V,
input pattern I)**. It splits:

- **PID half** (species/nature/shininess) = `generate_wild(advance(V, offset))`.
  We enumerate **all** 2³² V, so we already reach **every** shiny PID — and the
  PID set is **state-independent**. Moving tiles gives us **no new PIDs**.
- **IV half** = RNG chain position at the `iv1/iv2` reads. A **VBlank fires
  mid-generation and inserts a variable number of RNG calls** (the "gap"); the
  gap depends on the **intra-frame cycle phase**, a function of **S** (tile
  animation, NPC sprites, coords), **I** (input/animation), and the seed-
  dependent nature-loop length. ⇒ For one timing env, each PID is locked to
  **exactly one** IV. **Change the timing env ⇒ re-roll the IV every PID gets**,
  same PID set. (Evidence: `ss5` offset = 59 vs earlier state = 71.)

**Therefore** the lever for a better rare-nature mon is **more independent IV
samples for the same Adamant/Jolly PIDs** — i.e. stack timing environments.

## Knobs, ranked by leverage

1. **Save-state tile / position** — strongest, most independent. Each grass tile
   ≈ a fresh ~5k IV samples for the same PIDs. Automatable (walk K steps, snap).
2. **Input / trigger pattern** (jiggle hold/rel/axis) — cheaper (no walking) but
   a smaller, more-correlated shift. *Step 0 decides if it's enough on its own.*
3. **Written seed V** — already exhausted; BUT we drop ~22% of candidates whose
   realized offset isn't in our `GEN_OFFSETS`. Fuller offset set = +22% free.
4. **TID/SID (SID editing)** — changes the shiny PID set entirely. **Off-table**
   (user wants pure RNG manip) unless revisited.
5. ~~Idle/lead frames~~ — frame-quantized; no intra-frame phase change. Skip.

## Architecture redesign (the main work)

Split the monolithic per-species script into a reusable 3-stage pipeline so
timing envs stack cheaply and resumably:

- **Stage 1 — enumerate once, cache.** Shiny gen-seeds `G` + PID + nature for
  (species, slots, TID/SID). State-independent → `.npz` cache. (~31 s Nidoran♂.)
- **Stage 2 — sample per env.** For each env (state and/or pattern): verify all
  cached candidates → append `(G, PID, nature, IV, env_id)` to a results DB.
  ~40 s/env, parallel, resumable.
- **Stage 3 — select.** Best over **all** accumulated samples, any metric.

Per-species scripts become thin configs over `shiny_grass_core.py`.

### Expected payoff

| Envs | IV samples | Expected dual-31 | Realistic best |
|---|---|---|---|
| 1 (today) | ~4.1k | ~1 | Adamant 11/31/6/31/10/10 |
| 5 | ~20k | ~20 | dual-31 w/ ~3×31 bulk, ideal nature |
| 10–15 | ~50–60k | ~50 | shot at 4×31 / strong-bulk dual-31 |

## Stretch (parked): kill the VBlank gap → offline-exact + instant

- **(a) Characterize the gap** = f(start phase, nature-loop length). Instrument
  the core; if predictable, enumerate the true global best offline (no verify).
- **(b) Deterministic trigger** (controlled step / Sweet Scent) to fix the phase
  ⇒ constant gap ⇒ IVs fully offline. See `gen3_rng.py` §5/§6.

## Plain speed wins

- Cache Stage-1 enum (`.npz`).
- Fuller auto-calibrated `GEN_OFFSETS` (fewer misses → faster verify, +22%).
- Offsets dominant-first; persistent worker cores (already).

---

## Task list (ordered)

- [x] **0. Validate premise + pick the knob** — `gba_env_coverage.py` +
  `gba_env_coverage2.py`. Result: IVs deterministic; tiles = COVERAGE knob, not
  IV-diversity; input-pattern rejected for IVs. (See findings log.)
- [x] **1. Refactor to Stage1/2/3** — `shiny_grass_core.py`:
  - [x] 1a. `enumerate_candidates(...)` → `.npz` cache. (5227 Nidoran♂, 31s, cached)
  - [x] 1b. `verify_env(state, offsets, candidates)` → rows.
  - [x] 1c. `select_best(metric)` + resumable jsonl results DB.
  - [~] 1d. New thin driver `hunt_nidoranm.py` (multi-env). Porting Spearow +
    deleting the old monolith scripts still TODO.
- [x] **2. Env generator** — `gba_make_envs.py`: walks a validated path, saves
  tile states, calibrates per-env offset clusters, writes `envs_route3.json`.
- [x] **3. Multi-env Nidoran♂ run** — 4 envs (offsets 59/39/29/19) → ~100%
  physical-viable coverage. **Found a better dual-31: Lonely 27/31/14/31/23/16**
  (vs the frail Adamant 11/31/6/31/10/10). Awaiting user pick.
- [x] **4. (PROMOTED from stretch) Deterministic IV model** — DONE & validated.
  **Mechanism (disassembly + measurement):** `src/main.c VBlankIntr()` calls
  `Random()` once per frame; `CreateBoxMon` reads `iv1=Random(); iv2=Random()`
  right after the PID loop (nothing between). With o1,o2,o3 = the 3 post-PID RNG
  outputs: **iv2 = o3** (env-independent — `gba_iv_struct.py`: 92/92 at offset 59);
  **iv1 = o1 if loop<T else o2**, T per-offset, with a ~3-loop ambiguous band
  (sub-frame φ0 jitter). So each candidate has exactly TWO possible IV sets, both
  offline-computable from G (iv2 fixed). Tools: `gba_iv_model3.py` (g1/g2 anchored
  search), `gba_iv_struct.py` (per-env threshold calib), `validate_iv_prediction.py`
  (held-out check). Model lives in `pokemon_agent/gen3_rng.py` (`wild_outcome`,
  `wild_outcome_both`, `calibrate_iv_threshold`). Integrated into
  `shiny_grass_core.py` (Stage1 caches G,pid,nature,iters,o1,o2,o3 +
  `predict_env_ivs` + `confirm_candidates`). **End-to-end offline Nidoran♂ hunt:
  enumerate+predict 31.5s, confirm top-80 in 5.4s, total 37s; every prediction
  matched emulator confirmation EXACTLY.** Result is always exact (top-K confirmed).
  NOTE the (faster) chain-analyzers replaced the planned single-step tracer — they
  yielded the mechanism + constants without slow stepping.
  **Realization-coverage knob:** offline ranking now reveals the true ceiling (a
  Jolly 29/31/30/31/25/3 surfaced) but delivering a specific candidate still needs
  an env whose offset reproduces it — add envs (offset diversity) to realize the
  absolute-ceiling variant.
  (Earlier "off-chain 56%" was a red herring: it was the VBlank `Random()` landing
  between iv1 and iv2, which the old *consecutive* search in `gba_iv_model2.py`
  couldn't see — never a reseed.)
- [x] **5. Spearow ported to offline path** — `shiny_grass_spearow.py` now uses
  the offline-IV pipeline (enumerate+predict, realize top-N across combos).
  Validated: best realizable = the caught Hasty 31/31/17/31/19/31 4×31, in 58.7s
  (cached). First-time enumerate 553s (66k candidates; cached after). Remaining
  optional: deterministic fixed-frame trigger (Route B); retire old probe scripts.

## Realizability ceiling (2026-05-30)

The offline model exposes each candidate's TWO IV variants (iv1=o1 vs o2). Which
one an env realizes depends on the trigger offset's threshold T (loop<T→o1,
loop≥T→o2). Achievable offsets via {tile states × jiggle patterns} span T≈[18,59]
(`probe_pattern.py`: LR1:1→offset ~98, LR2:1→59/39/29/19, etc.). So a candidate's
variant B is realizable only when loop ≥ ~18, variant A only when loop ≤ ~55.
`best_realizable_nidoran.py` ranks the space offline then brute-realizes the
top-120 across 6 combos. **Conclusion: the best REALIZABLE physical Nidoran♂ is
the already-delivered Lonely 27/31/14/31/23/16 (Atk31&Spe31, +Atk, HP27);** the
math-ceiling Jolly 29/31/30/31/25/3 is **un-realizable** (loop 15 < T-floor ~18).
Mild 27/31/31/30/13/29 is the bulkiest alternative (Def31/SpD29, Spe 1 off). The
realizable ceiling = the delivered mon; no env coverage beats it.

## Decisions / findings log

- 2026-05-30: Plan created. User: prefer fastest knob that consistently widens
  IV coverage (timing vs tiles — decide empirically in step 0). Stretch parked;
  focus the refactor first. SID editing remains off-table.
- 2026-05-30: **Step 0 result (`gba_env_coverage.py`).** Premise CONFIRMED but
  knob decided: **INPUT-pattern variation is rejected for IV diversity** — same
  offset + different axis (UD vs LR @ offset 59) gave identical IV for 100% of
  shared G (0% change); different hold/rel only shifts the *offset* (got 40/59/96)
  so it reaches *different* G, not new IVs for a fixed G. **TILE variation is the
  knob**: 1 step up (offset 39) changed the IV for **15%** of shared G. Caveats:
  (a) only ~15%/step ⇒ envs are partially correlated, not independent — payoff
  table was optimistic; (b) walking can leave the grass (TILE_down invalid) so
  env generation must validate in-grass. Next: measure the saturation curve over
  more valid tiles to size the real payoff (and reconsider un-parking the stretch
  gap-kill, which would give the full per-G IV range directly).
- Side note: input-pattern offset control (40–96) is still useful to **recover
  the ~22% of candidates** that don't reproduce at the dominant offset (run a
  second pattern), independent of IV diversity.
- 2026-05-30: **Step 0b result (`gba_env_coverage2.py`) — STRATEGY PIVOT.**
  Tile coverage SATURATES at **1.12 distinct IVs/G** and does NOT grow past 2
  envs (1.12 @ 2/3/4 envs). Split by nature-loop length: **short-loop = 0% IV
  change** across tiles, **long-loop = 20%**. ⇒ **IVs are ~deterministic per
  seed** (short-loop fixed; long-loop has ≤1 alternate). Therefore:
  * **Tiles are a COVERAGE knob, not an IV-diversity knob.** Each tile has a
    different offset cluster (59/39/29/19), reproducing a different ~78% subset
    of the FIXED 5,227-mon shiny-Nidoran♂ universe. Union ~4–5 tiles ⇒ ~full
    coverage ⇒ see every dual-31 that exists (~5 total) and pick best bulk.
  * **Ceiling (no SID edit):** ~5,227 mons, ~5 with Atk31&Spe31; a 4×31 likely
    doesn't exist in that set. Better-than-current = best-of-~5 dual-31, bounded.
  * **Gap-kill is now the headline unlock, and tractable:** IVs deterministic ⇒
    correct G→IV is offline-computable; `generate_wild`'s IV read is just
    mis-offset (true gap > the 0–15 the probe searched). Fix → instant exact best.
  * **Revised lever ranking:** (1) full-coverage multi-tile/offset verify [does
    the better-Nidoran now], (2) deterministic IV model [instant + exact, the
    real unlock], (3) input-pattern only — rejected for IVs, minor for coverage.
- 2026-05-30: **Refactor done + multi-env run (`shiny_grass_core.py` +
  `hunt_nidoranm.py`).** Pipeline validated end-to-end. 4 envs (offsets
  59/39/29/19); env03 alone reproduced 5221/5227, union ≈ 100% of physical-viable
  universe. Surfaced a **better dual-31: Lonely 27/31/14/31/23/16** (Atk31+Spe31,
  +Atk nature, HP27 — much bulkier than the prior Adamant 11/31/6/31/10/10). Also
  notable: Mild 27/31/31/30/13/29, Serious 10/25/31/31/31/9 (#31=3). Confirms the
  ceiling: ~a couple usable dual-31s; no 4×31 exists at this TID/SID. Cache
  `cache_nidoranm.npz`, results `results_nidoranm.jsonl`.
