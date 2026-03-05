"""Quick smoke test for imports and basic functionality."""
from pokemon_agent import __version__
from pokemon_agent.pathfinding import find_path, navigate
from pokemon_agent.memory.reader import GameMemoryReader

print(f"pokemon-agent v{__version__}")
print("Core imports OK")

# Test pathfinding
path = find_path((0, 0), (3, 2), None)
print(f"Pathfinding test: (0,0)->(3,2) = {path}")
actions = navigate((0, 0), (3, 2))
print(f"Actions: {actions}")
print("All basic tests passed")
