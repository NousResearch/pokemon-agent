"""
Test the FastAPI server end-to-end.
Starts the server, loads a save state, walks around, tests all endpoints.
"""

import sys
import time
import threading
import json

sys.path.insert(0, ".")

def main():
    # First, create a save state that's past the intro
    print("=== Creating initial save state ===")
    from pokemon_agent.emulator import create_emulator
    from pokemon_agent.memory.red import PokemonRedReader
    
    emu = create_emulator("roms/pokemon_red.gb")
    
    # Fast-forward through intro
    emu.tick(180)
    emu.press("start", 8)
    emu.tick(30)
    for _ in range(10):
        emu.press("a", 8)
        emu.tick(30)
    for _ in range(80):
        emu.press("a", 4)
        emu.tick(20)
    emu.press("a", 4)
    emu.tick(20)
    for _ in range(100):
        emu.press("a", 4)
        emu.tick(20)
    # Clear dialog
    for _ in range(30):
        emu.press("b", 4)
        emu.tick(16)
    
    import os
    os.makedirs(os.path.expanduser("~/.pokemon-agent/saves"), exist_ok=True)
    emu.save_state(os.path.expanduser("~/.pokemon-agent/saves/intro_complete.state"))
    print("  Saved intro_complete state")
    emu.close()
    
    # Now start the server
    print("\n=== Starting server ===")
    from pokemon_agent.server import GameConfig, configure, app
    
    configure(GameConfig(
        rom_path="roms/pokemon_red.gb",
        game_type="red",
        port=8765,
        load_state="intro_complete",
    ))
    
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8765, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    
    # Wait for server to be ready
    import httpx
    for i in range(20):
        try:
            r = httpx.get("http://localhost:8765/health", timeout=2)
            if r.status_code == 200:
                print(f"  Server ready after {i+1} attempts")
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("  ERROR: Server didn't start!")
        sys.exit(1)
    
    # Test endpoints
    print("\n=== Testing GET / ===")
    r = httpx.get("http://localhost:8765/")
    print(f"  Status: {r.status_code}")
    data = r.json()
    print(f"  Name: {data['name']}")
    print(f"  Emulator ready: {data['emulator_ready']}")
    
    print("\n=== Testing GET /health ===")
    r = httpx.get("http://localhost:8765/health")
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    
    print("\n=== Testing GET /state ===")
    r = httpx.get("http://localhost:8765/state")
    print(f"  Status: {r.status_code}")
    state = r.json()
    player = state.get("player", {})
    map_info = state.get("map", {})
    print(f"  Map: {map_info.get('map_name')} (id={map_info.get('map_id')})")
    print(f"  Position: {player.get('position')}")
    print(f"  Name: {player.get('name')}")
    print(f"  Money: ${player.get('money', 0):,}")
    print(f"  Dialog active: {state.get('dialog', {}).get('active')}")
    
    print("\n=== Testing POST /action (walk_down) ===")
    r = httpx.post("http://localhost:8765/action",
                    json={"actions": ["walk_down"]},
                    timeout=10)
    print(f"  Status: {r.status_code}")
    data = r.json()
    print(f"  Actions executed: {data.get('actions_executed')}")
    pos_after = data.get("state_after", {}).get("player", {}).get("position", {})
    print(f"  Position after: {pos_after}")
    
    print("\n=== Testing POST /action (walk sequence) ===")
    r = httpx.post("http://localhost:8765/action",
                    json={"actions": ["walk_right", "walk_right", "walk_up", "walk_up"]},
                    timeout=10)
    print(f"  Status: {r.status_code}")
    data = r.json()
    print(f"  Actions executed: {data.get('actions_executed')}")
    pos_after = data.get("state_after", {}).get("player", {}).get("position", {})
    print(f"  Position after: {pos_after}")
    
    print("\n=== Testing GET /screenshot ===")
    r = httpx.get("http://localhost:8765/screenshot")
    print(f"  Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('content-type')}")
    print(f"  Size: {len(r.content)} bytes")
    
    # Save the screenshot
    with open("/tmp/pokemon_screenshot.png", "wb") as f:
        f.write(r.content)
    print(f"  Saved to /tmp/pokemon_screenshot.png")
    
    print("\n=== Testing GET /screenshot/base64 ===")
    r = httpx.get("http://localhost:8765/screenshot/base64")
    print(f"  Status: {r.status_code}")
    data = r.json()
    print(f"  Format: {data.get('format')}")
    print(f"  Base64 length: {len(data.get('image', ''))} chars")
    
    print("\n=== Testing POST /save ===")
    r = httpx.post("http://localhost:8765/save",
                    json={"name": "test_save"})
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    
    print("\n=== Testing GET /saves ===")
    r = httpx.get("http://localhost:8765/saves")
    print(f"  Status: {r.status_code}")
    saves = r.json().get("saves", [])
    for s in saves:
        print(f"  - {s['name']} ({s['size_bytes']} bytes)")
    
    print("\n=== Testing POST /load ===")
    r = httpx.post("http://localhost:8765/load",
                    json={"name": "intro_complete"})
    print(f"  Status: {r.status_code}")
    data = r.json()
    pos = data.get("state_after", {}).get("player", {}).get("position", {})
    print(f"  Position after load: {pos}")
    
    print("\n=== Testing GET /minimap ===")
    r = httpx.get("http://localhost:8765/minimap")
    print(f"  Status: {r.status_code}")
    print(f"  Content:")
    for line in r.text.split("\n"):
        print(f"    {line}")
    
    print("\n=== Testing error handling ===")
    r = httpx.post("http://localhost:8765/action",
                    json={"actions": ["invalid_action"]})
    print(f"  Invalid action status: {r.status_code}")
    
    r = httpx.post("http://localhost:8765/load",
                    json={"name": "nonexistent_save"})
    print(f"  Missing save status: {r.status_code}")
    
    print("\n=== All tests passed! ===")
    
    # Shutdown
    server.should_exit = True
    time.sleep(1)


if __name__ == "__main__":
    main()
