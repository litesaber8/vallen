"""
Vallen — MCP Server.
Exposes the game state and actions via a JSON-RPC interface.
"""

import json
import sys
from typing import Any, Dict, List
import model
import interface
from turn_manager import TurnManager

class VallenMCPServer:
    def __init__(self, state: model.GameState):
        self.state = state
        self.tm = TurnManager()

    def get_state_serialized(self) -> Dict[str, Any]:
        """Serializes the GameState for external agents."""
        # Basic serialization of the GameState
        return {
            "turn": self.state.turn_number,
            "phase": self.state.phase.name,
            "active_player": self.state.active.name,
            "players": [
                {
                    "name": p.name,
                    "lp": p.lp,
                    "field": [
                        {"id": u.card.id, "name": u.card.name, "hp": u.current_hp, "mode": u.mode.name}
                        if u else None for u in p.unit_zones
                    ],
                    "hand_count": len(p.hand)
                } for p in self.state.players
            ]
        }

    def get_legal_actions_canonical(self) -> List[Dict[str, Any]]:
        """Returns all legal actions in the canonical schema."""
        state = self.state
        player = state.active
        actions = []

        # 1. Handle Pending Event Window
        if state.pending_event is not None:
            # Only counter_support and pass_response are legal
            # Counter support needs to be checked via interface
            for card, event in interface.legal_counters(state):
                actions.append({"action": "counter_support", "card_id": card.id})

            actions.append({"action": "pass_response"})
            return actions

        # 2. Normal Turn Actions
        # Normal Summons
        for card, tributes in interface.legal_normal_summons(player):
            actions.append({"action": "normal_summon", "card_id": card.id})

        # Level Ups
        for material, card in interface.legal_level_ups(player):
            actions.append({"action": "level_up", "unit_id": material.uid, "card_id": card.id})

        # Mode Switches
        for unit in interface.legal_mode_switches(player):
            actions.append({"action": "switch_mode", "unit_id": unit.uid})

        # Attacks
        for attacker, defender in interface.legal_attacks(state):
            actions.append({
                "action": "attack",
                "attacker_id": attacker.uid,
                "defender_id": defender.uid if defender else None
            })

        # End Phase
        actions.append({"action": "end_phase"})

        return actions

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        method = request.get("method")
        params = request.get("params", {})

        if method == "get_state":
            return {"result": self.get_state_serialized()}

        elif method == "legal_actions":
            return {"result": self.get_legal_actions_canonical()}

        elif method == "execute_action":
            action = params.get("action")
            try:
                result = self.tm.validate_and_execute(self.state, action)
                return {"result": {"status": "success", "output": str(result)}}
            except Exception as e:
                return {"error": {"code": -32000, "message": str(e)}}

        elif method == "next_turn":
            self.tm.next_turn(self.state)
            return {"result": {"status": "success"}}

        else:
            return {"error": {"code": -32601, "message": "Method not found"}}

    def run(self):
        """Main loop for the MCP server (STDIO JSON-RPC)."""
        # Note: In a real MCP environment, this would follow the MCP spec exactly.
        # For this implementation, we use a simplified JSON-RPC over stdin/stdout.
        for line in sys.stdin:
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps({"error": "Invalid JSON"}) + "\n")
                sys.stdout.flush()

if __name__ == "__main__":
    # Setup a basic state for the server to manage
    import cards
    user = model.Player(name="User", faction="Humanity", deck=[])
    ai = model.Player(name="AI", faction="Iron Recursion", deck=[])
    user.hand = [cards.CONSCRIPT]
    state = model.GameState(players=(user, ai))

    server = VallenMCPServer(state)
    server.run()
