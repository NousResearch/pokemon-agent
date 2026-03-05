"""Event logging and history for the Hermes Plays Pokémon dashboard."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class EventLogger:
    """Logs game events to a JSONL file for history and replay.

    Each event has: timestamp, turn_number, type, data.
    Supports action logging, reasoning, key moments, and battles.
    Auto-detects key moments like badge changes and party changes.
    """

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = Path(log_path or "pokemon_events.jsonl")
        self.turn_number = 0
        self._last_badge_count = 0
        self._last_party_size = 0
        self._stats_cache = None
        self._stats_cache_time = 0

    def _make_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a structured event dict."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "turn_number": self.turn_number,
            "type": event_type,
            "data": data,
        }

    def _write_event(self, event: Dict[str, Any]):
        """Append an event to the JSONL log file."""
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(event) + "\n")
            self._stats_cache = None  # invalidate cache
        except Exception as e:
            logger.error(f"Failed to write event: {e}")

    def log_action(
        self,
        action: str,
        state_before: Optional[Dict] = None,
        state_after: Optional[Dict] = None,
    ):
        """Log a game action (button press, tool call, etc.)."""
        self.turn_number += 1
        event = self._make_event(
            "action",
            {
                "action": action,
                "state_before": _compact_state(state_before),
                "state_after": _compact_state(state_after),
            },
        )
        self._write_event(event)
        # Auto-detect key moments from state transitions
        if state_before and state_after:
            self._detect_key_moments(state_before, state_after)

    def log_reasoning(self, text: str):
        """Log AI reasoning / thinking text."""
        event = self._make_event("reasoning", {"text": text})
        self._write_event(event)

    def log_key_moment(
        self,
        description: str,
        category: str = "milestone",
        screenshot_path: Optional[str] = None,
    ):
        """Log a key moment (badge earned, pokemon caught, etc.)."""
        event = self._make_event(
            "key_moment",
            {
                "description": description,
                "category": category,
                "screenshot_path": screenshot_path,
            },
        )
        self._write_event(event)
        logger.info(f"Key moment: {description}")

    def log_battle(self, opponent: str, result: str, details: Optional[Dict] = None):
        """Log a battle outcome."""
        event = self._make_event(
            "battle",
            {
                "opponent": opponent,
                "result": result,  # "win", "lose", "flee", "catch"
                "details": details or {},
            },
        )
        self._write_event(event)

    def _detect_key_moments(self, before: Dict, after: Dict):
        """Auto-detect key moments from state changes."""
        b_player = before.get("player", {})
        a_player = after.get("player", {})

        # Badge change
        b_badges = b_player.get("badges", 0)
        a_badges = a_player.get("badges", 0)
        if isinstance(a_badges, int) and isinstance(b_badges, int):
            if a_badges > b_badges:
                badges_list = a_player.get("badges_list", [])
                new_badge = badges_list[-1] if badges_list else f"Badge #{a_badges}"
                self.log_key_moment(
                    f"Earned {new_badge} Badge! ({a_badges}/8)",
                    category="badge",
                )

        # Party size change (new pokemon)
        b_party = len(before.get("party", []))
        a_party = len(after.get("party", []))
        if a_party > b_party:
            party = after.get("party", [])
            if party:
                new_mon = party[-1].get("nickname", party[-1].get("species", "???"))
                self.log_key_moment(
                    f"Caught {new_mon}! (Party: {a_party}/6)",
                    category="catch",
                )

    def get_history(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Read events back from the JSONL log."""
        if not self.log_path.exists():
            return []
        events = []
        try:
            with open(self.log_path, "r") as f:
                lines = f.readlines()
            start = max(0, len(lines) - offset - limit)
            end = len(lines) - offset
            for line in lines[start:end]:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to read history: {e}")
        return events

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate stats from the event log."""
        now = time.time()
        if self._stats_cache and (now - self._stats_cache_time) < 5:
            return self._stats_cache

        stats = {
            "total_turns": 0,
            "battles_won": 0,
            "battles_lost": 0,
            "battles_fled": 0,
            "pokemon_caught": 0,
            "badges_earned": 0,
            "key_moments": [],
        }

        if not self.log_path.exists():
            return stats

        try:
            with open(self.log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    data = event.get("data", {})

                    if etype == "action":
                        stats["total_turns"] += 1
                    elif etype == "battle":
                        result = data.get("result", "")
                        if result == "win":
                            stats["battles_won"] += 1
                        elif result == "lose":
                            stats["battles_lost"] += 1
                        elif result == "flee":
                            stats["battles_fled"] += 1
                        elif result == "catch":
                            stats["pokemon_caught"] += 1
                    elif etype == "key_moment":
                        cat = data.get("category", "")
                        if cat == "badge":
                            stats["badges_earned"] += 1
                        elif cat == "catch":
                            stats["pokemon_caught"] += 1
                        stats["key_moments"].append(
                            {
                                "description": data.get("description", ""),
                                "category": cat,
                                "timestamp": event.get("timestamp", ""),
                                "turn": event.get("turn_number", 0),
                            }
                        )
        except Exception as e:
            logger.error(f"Failed to compute stats: {e}")

        self._stats_cache = stats
        self._stats_cache_time = now
        return stats


def _compact_state(state: Optional[Dict]) -> Optional[Dict]:
    """Create a compact version of state for logging (skip large fields)."""
    if not state:
        return None
    compact = {}
    player = state.get("player")
    if player:
        compact["player"] = {
            "position": player.get("position"),
            "badges": player.get("badges"),
            "money": player.get("money"),
        }
    party = state.get("party")
    if party:
        compact["party_summary"] = [
            {"name": p.get("nickname", p.get("species", "?")), "hp": p.get("hp"), "max_hp": p.get("max_hp")}
            for p in party
        ]
    if state.get("battle"):
        compact["in_battle"] = True
    if state.get("dialog", {}).get("active"):
        compact["dialog_active"] = True
    return compact
