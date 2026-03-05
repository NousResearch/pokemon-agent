"""
Pokemon Agent — CLI entry point.

Usage:
    pokemon-agent serve --rom path/to/rom.gba [--port 8765] [--data-dir ~/.pokemon-agent]
    pokemon-agent info  --rom path/to/rom.gba
    pokemon-agent --version
"""

import argparse
import hashlib
import sys
from pathlib import Path

__version__ = "0.1.0"

BANNER = r"""
  ____       _                              _                    _
 |  _ \ ___ | | _____ _ __ ___   ___  _ __ / \   __ _  ___ _ __ | |_
 | |_) / _ \| |/ / _ \ '_ ` _ \ / _ \| '_ / _ \ / _` |/ _ \ '_ \| __|
 |  __/ (_) |   <  __/ | | | | | (_) | | / ___ \ (_| |  __/ | | | |_
 |_|   \___/|_|\_\___|_| |_| |_|\___/|_|/_/   \_\__, |\___|_| |_|\__|
                                                  |___/  v{version}
"""


def _detect_game_type(rom_path: str) -> str:
    ext = Path(rom_path).suffix.lower()
    if ext in (".gb", ".gbc"):
        return "red"
    elif ext == ".gba":
        return "firered"
    return "unknown"


def cmd_serve(args):
    """Start the FastAPI game server."""
    rom = Path(args.rom).expanduser().resolve()
    if not rom.exists():
        print(f"ERROR: ROM file not found: {rom}", file=sys.stderr)
        sys.exit(1)

    data_dir = Path(args.data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "saves").mkdir(exist_ok=True)

    game_type = _detect_game_type(str(rom))

    print(BANNER.format(version=__version__))
    print(f"  ROM:       {rom}")
    print(f"  Game type: {game_type}")
    print(f"  Port:      {args.port}")
    print(f"  Data dir:  {data_dir}")
    print()

    # Configure the server before uvicorn imports the app
    from pokemon_agent.server import GameConfig, configure, app  # noqa: F811

    configure(GameConfig(
        rom_path=str(rom),
        game_type=game_type,
        port=args.port,
        data_dir=str(data_dir),
    ))

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


def cmd_info(args):
    """Display ROM information."""
    rom = Path(args.rom).expanduser().resolve()
    if not rom.exists():
        print(f"ERROR: ROM file not found: {rom}", file=sys.stderr)
        sys.exit(1)

    game_type = _detect_game_type(str(rom))
    size = rom.stat().st_size

    # Compute SHA-256
    sha = hashlib.sha256()
    with open(rom, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)

    print(f"ROM path:     {rom}")
    print(f"File size:    {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
    print(f"SHA-256:      {sha.hexdigest()}")
    print(f"Extension:    {rom.suffix}")
    print(f"Detected as:  {game_type}")


def main():
    parser = argparse.ArgumentParser(
        prog="pokemon-agent",
        description="Pokemon Agent — AI-powered Pokemon game controller",
    )
    parser.add_argument(
        "--version", action="version", version=f"pokemon-agent {__version__}"
    )

    sub = parser.add_subparsers(dest="command")

    # --- serve ---
    serve_p = sub.add_parser("serve", help="Start the game server")
    serve_p.add_argument("--rom", required=True, help="Path to Pokemon ROM file")
    serve_p.add_argument("--port", type=int, default=8765, help="Server port (default: 8765)")
    serve_p.add_argument(
        "--data-dir", default="~/.pokemon-agent",
        help="Data directory for saves, etc. (default: ~/.pokemon-agent)",
    )
    serve_p.add_argument(
        "--no-dashboard", action="store_true",
        help="Disable dashboard mounting",
    )

    # --- info ---
    info_p = sub.add_parser("info", help="Show ROM information")
    info_p.add_argument("--rom", required=True, help="Path to Pokemon ROM file")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "info":
        cmd_info(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
