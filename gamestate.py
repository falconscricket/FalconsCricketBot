"""
gamestate.py — Enums and dataclasses describing an in-progress match.
All live sessions are held in memory (module-level dict) and mirrored to
the database on every mutating event so a restart can be recovered from.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class GameMode(Enum):
    ONE_V_ONE = auto()
    SOLO_TOURNAMENT = auto()
    TEAM_MATCH = auto()


class GamePhase(Enum):
    LOBBY = auto()          # waiting for players to join
    TOSS = auto()           # coin toss in progress
    INNINGS_1 = auto()
    INNINGS_BREAK = auto()
    INNINGS_2 = auto()
    FINISHED = auto()


class Team(Enum):
    A = "A"
    B = "B"
    NONE = "NONE"           # used for 1v1 / solo where there's no team split


@dataclass
class Player:
    user_id: int
    name: str
    team: Team = Team.NONE
    runs: int = 0
    balls_faced: int = 0
    wickets_taken: int = 0
    balls_bowled: int = 0
    is_out: bool = False

    @property
    def strike_rate(self) -> float:
        if self.balls_faced == 0:
            return 0.0
        return round((self.runs / self.balls_faced) * 100, 2)


@dataclass
class BallEvent:
    over_number: int
    ball_number: int
    bowler_id: int
    batter_id: int
    runs: int
    is_wide: bool = False
    is_wicket: bool = False
    is_free_hit: bool = False
    powerplay_bonus: int = 0


@dataclass
class InningsState:
    batting_team: Team
    bowling_team: Team
    total_runs: int = 0
    wickets: int = 0
    legal_balls: int = 0
    ball_log: list[BallEvent] = field(default_factory=list)
    current_batter_id: Optional[int] = None
    non_striker_id: Optional[int] = None
    current_bowler_id: Optional[int] = None
    free_hit_active: bool = False
    pending_bowler_digit: Optional[str] = None  # locked-in bowl awaiting batter
    last_ball_time: float = field(default_factory=time.time)

    @property
    def overs_display(self) -> str:
        overs = self.legal_balls // 6
        balls = self.legal_balls % 6
        return f"{overs}.{balls}"


@dataclass
class MatchSession:
    chat_id: int
    mode: GameMode
    phase: GamePhase = GamePhase.LOBBY
    host_id: Optional[int] = None
    players: dict[int, Player] = field(default_factory=dict)
    team_a: list[int] = field(default_factory=list)
    team_b: list[int] = field(default_factory=list)
    target: Optional[int] = None
    innings_1: Optional[InningsState] = None
    innings_2: Optional[InningsState] = None
    powerplay_active: bool = False
    over_length: int = 6  # balls per bowler spell in solo tournament (1 or 3 also allowed)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    host_last_action: float = field(default_factory=time.time)
    winner: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    # --- Solo Tournament automatic rotation state ---
    # team_a is reused as the fixed join-order roster for this mode.
    tourney_batter_ptr: int = 0   # index in team_a of the CURRENT batter
    tourney_bowler_ptr: int = 0   # index in team_a of the CURRENT bowler
    spell_balls: int = 0          # legal balls the current bowler has bowled in this spell
    left_players: set[int] = field(default_factory=set)  # left via /leave or 2nd foul — never re-enter

    @property
    def current_innings(self) -> Optional[InningsState]:
        if self.phase == GamePhase.INNINGS_1:
            return self.innings_1
        if self.phase == GamePhase.INNINGS_2:
            return self.innings_2
        return None


# chat_id -> MatchSession  (single active match per chat)
SESSIONS: dict[int, MatchSession] = {}

# user_id -> chat_id, so a player's PM reply (bowling digit) can be routed
# back to the correct match even though it was sent in a private chat.
PM_ROUTES: dict[int, int] = {}


def get_session(chat_id: int) -> Optional[MatchSession]:
    return SESSIONS.get(chat_id)


def create_session(chat_id: int, mode: GameMode, host_id: Optional[int]) -> MatchSession:
    session = MatchSession(chat_id=chat_id, mode=mode, host_id=host_id)
    SESSIONS[chat_id] = session
    return session


def end_session(chat_id: int) -> None:
    session = SESSIONS.pop(chat_id, None)
    if session:
        for uid in session.players:
            if PM_ROUTES.get(uid) == chat_id:
                PM_ROUTES.pop(uid, None)
