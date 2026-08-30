"""Minimal heuristic stubs needed by the reclaim test."""

def choose_reclaim_from_discard(player):
    if player.discard_pile:
        return player.discard_pile[0]
    return None
