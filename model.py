"""
Compact Card Game — core data model.
Card is immutable (pure definition). UnitState/SupportState hold all mutable
in-game state so effects can never accidentally mutate a card definition.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Dict, Any


class CardType(Enum):
    UNIT = auto()
    SUPPORT = auto()


class Mode(Enum):
    ATTACK = auto()
    DEFENSE = auto()


class SupportType(Enum):
    NORMAL = auto()
    EQUIP = auto()
    FIELD = auto()
    COUNTER = auto()


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    faction: str
    card_type: CardType
    level: int
    base_ap: int = 0
    base_hp: int = 0
    support_type: Optional[SupportType] = None
    abilities: tuple = field(default_factory=tuple)


@dataclass
class UnitState:
    uid: str
    card: Card
    owner: "Player"
    current_hp: int
    mode: Mode = Mode.ATTACK
    level_up_unlocked: bool = False
    built_from: Optional[Card] = None
    has_attacked: bool = False
    attached_equips: list = field(default_factory=list)

    @property
    def max_hp(self) -> int:
        return self.card.base_hp

    @property
    def ap(self) -> int:
        return self.card.base_ap



@dataclass
class EquipState:
    card: Card
    owner: "Player"
    attached_to: "UnitState"


@dataclass
class ResourcePileCard:

    """A destroyed Unit sitting in the Resource Pile.
    Tribute value is always 1, regardless of printed level.
    """
    card: Card

    @property
    def value(self) -> int:
        return 1


@dataclass
class Player:
    name: str
    faction: str
    deck: list
    hand: list = field(default_factory=list)
    unit_zones: list = field(default_factory=list)
    support_zones: list = field(default_factory=list)
    resource_pile: list = field(default_factory=list)
    discard_pile: list = field(default_factory=list)
    lp: int = 4000
    # New rule (explicitly frozen, not previously part of the ruleset):
    # at most one unit-card action (Normal Summon OR Level-Up Summon) per
    # turn, never both, never chained. Reset to False at the start of each
    # of this player's turns by TurnManager.next_turn().
    unit_action_used_this_turn: bool = False


    def __post_init__(self):
        if not self.unit_zones:
            self.unit_zones = [None, None, None]
        if not self.support_zones:
            self.support_zones = [None, None, None]

    def field_units(self):
        return [u for u in self.unit_zones if u is not None]

    def empty_zone_index(self):
        for i, z in enumerate(self.unit_zones):
            if z is None:
                return i
        return None

    def empty_support_zone_index(self):
        for i, z in enumerate(self.support_zones):
            if z is None:
                return i
        return None


class Phase(Enum):
    DRAW = auto()
    MAIN = auto()
    BATTLE = auto()
    END = auto()


@dataclass
class GameState:
    players: tuple
    active_idx: int = 0
    turn_number: int = 0
    phase: Phase = Phase.DRAW
    log: list = field(default_factory=list)
    game_over: bool = False
    winner: Optional[str] = None
    pending_event: Optional[Dict[str, Any]] = None


    @property
    def active(self) -> Player:
        return self.players[self.active_idx]

    @property
    def opponent(self) -> Player:
        return self.players[1 - self.active_idx]

    def emit(self, line: str):
        self.log.append(line)


class InvariantError(Exception):
    """Raised the instant the engine detects a state that the frozen rules
    do not permit. This is independent of *why* an action was chosen —
    the heuristic layer never gets consulted here."""
    pass
