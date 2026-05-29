"""Boot Pokemon LeafGreen in a visible window (mGBA via pygame/SDL2).

Unlike PyBoy, mGBA's Python bindings have no built-in window, so this
script renders the framebuffer and feeds input through pygame (which is
SDL2 under the hood).

  ⚠️  Run it INSIDE the devbox, with the GBA venv:
      distrobox enter devbox -- \
        /var/home/karce/Projects/pokemon-agent/.venv-gba/bin/python play_gba.py

Controls
--------
  Arrow keys   — D-Pad
  Z            — A
  X            — B
  Enter        — Start
  Backspace    — Select
  Q / W        — L / R shoulders
  Space (hold) — turbo / fast-forward
  Esc / close  — quit

Save states (written with mGBA's raw-state format — the exact format the
shiny scripts load):
  1-9          — LOAD slot N   (roms/leafgreen.state<N>)
  Shift + 1-9  — SAVE slot N
  F5           — SAVE the canonical starter-reset state
                 (roms/leafgreen_starter.state)
  F9           — LOAD roms/leafgreen_starter.state

For the shiny *starter reset* hunt: play up to the moment right before you
confirm your starter (Oak's last "Are you sure?" / the frame just before
the Pokémon is handed over), then press F5.  That's the state the shiny
script will reload and re-roll from.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Avoid SDL trying to open an audio device that doesn't exist in the container.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import mgba.core
import mgba.image
import mgba.log

import pygame

ROOT = Path(__file__).resolve().parent
DEFAULT_ROM = ROOT / "roms" / "Pokemon - LeafGreen Version (USA).gba"
STARTER_STATE = ROOT / "roms" / "leafgreen_starter.state"


def slot_path(n: int) -> Path:
    return ROOT / "roms" / f"leafgreen.state{n}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Play Pokemon LeafGreen (mGBA window).")
    p.add_argument("--rom", default=str(DEFAULT_ROM), help="Path to the .gba ROM.")
    p.add_argument("--scale", type=int, default=3, help="Window scale factor.")
    p.add_argument("--turbo", type=int, default=8,
                   help="Frames emulated per displayed frame while holding Space.")
    p.add_argument("--load", default=None,
                   help="Raw state file to load on boot (e.g. roms/leafgreen_starter.state).")
    return p.parse_args(argv)


# Keyboard → GBA key-index map (indices per mGBA: A=0 B=1 Sel=2 Start=3
# Right=4 Left=5 Up=6 Down=7 R=8 L=9).  Held state is read every frame.
def held_gba_keys(core, pressed) -> list[int]:
    m = {
        pygame.K_UP: core.KEY_UP,
        pygame.K_DOWN: core.KEY_DOWN,
        pygame.K_LEFT: core.KEY_LEFT,
        pygame.K_RIGHT: core.KEY_RIGHT,
        pygame.K_z: core.KEY_A,
        pygame.K_x: core.KEY_B,
        pygame.K_RETURN: core.KEY_START,
        pygame.K_BACKSPACE: core.KEY_SELECT,
        pygame.K_q: core.KEY_L,
        pygame.K_w: core.KEY_R,
    }
    return [gba_key for sdl_key, gba_key in m.items() if pressed[sdl_key]]


def save_state(core, path: Path) -> None:
    try:
        data = bytes(core.save_raw_state())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"[save] {path}  ({len(data)} bytes)")
    except Exception as e:  # noqa: BLE001
        print(f"[save] FAILED → {path}: {e}", file=sys.stderr)


def load_state(core, path: Path) -> None:
    if not path.exists():
        print(f"[load] no state at {path}", file=sys.stderr)
        return
    try:
        core.load_raw_state(path.read_bytes())
        print(f"[load] {path}")
    except Exception as e:  # noqa: BLE001
        print(f"[load] FAILED ← {path}: {e}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    rom = Path(args.rom)
    if not rom.exists():
        print(f"ERROR: ROM not found at {rom}", file=sys.stderr)
        return 1

    mgba.log.silence()
    core = mgba.core.load_path(str(rom))
    if core is None:
        print(f"ERROR: mGBA failed to load {rom}", file=sys.stderr)
        return 1

    width, height = core.desired_video_dimensions()
    fb = mgba.image.Image(width, height)
    core.set_video_buffer(fb)
    core.reset()

    if args.load:
        load_state(core, Path(args.load))

    pygame.display.init()
    pygame.display.set_caption("Pokemon LeafGreen — mGBA")
    win = pygame.display.set_mode((width * args.scale, height * args.scale))
    clock = pygame.time.Clock()

    print(__doc__)
    print(f"Loaded {rom.name} at {width}x{height}, scale {args.scale}x.")

    running = True
    while running:
        turbo = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F5:
                    save_state(core, STARTER_STATE)
                elif event.key == pygame.K_F9:
                    load_state(core, STARTER_STATE)
                elif pygame.K_1 <= event.key <= pygame.K_9:
                    n = event.key - pygame.K_0
                    if event.mod & pygame.KMOD_SHIFT:
                        save_state(core, slot_path(n))
                    else:
                        load_state(core, slot_path(n))

        pressed = pygame.key.get_pressed()
        if pressed[pygame.K_ESCAPE]:
            running = False
        turbo = bool(pressed[pygame.K_SPACE])

        core.set_keys(*held_gba_keys(core, pressed))

        # Emulate one (or several, in turbo) frames before drawing.
        steps = args.turbo if turbo else 1
        for _ in range(steps):
            core.run_frame()

        rgb = fb.to_pil().convert("RGB")
        # .convert() matches the display's pixel format so we can scale
        # straight into the window surface (formats must match).
        frame = pygame.image.frombuffer(rgb.tobytes(), (width, height), "RGB").convert()
        pygame.transform.scale(frame, win.get_size(), win)
        pygame.display.flip()

        # Cap at 60 fps normally; let turbo run as fast as it can.
        if not turbo:
            clock.tick(60)

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
