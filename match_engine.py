"""
match_engine.py — Pure game-logic functions: evaluating a delivery,
rotating strike, computing targets, and deciding match outcomes.
Kept free of Telegram API calls so it can be unit-tested in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import BALLS_PER_OVER, POWERPLAY_BONUS_RUNS, POWERPLAY_TRIGGER_RUNS
from gamestate import BallEvent, InningsState


@dataclass
class DeliveryResult:
    event: BallEvent
    is_wicket: bool
    is_wide: bool
    runs_scored: int
    rotate_strike: bool
    over_completed: bool
    message: str


def evaluate_delivery(
    innings: InningsState,
    bowler_digit: str,
    batter_digit: str,
    powerplay_active: bool,
) -> DeliveryResult:
    """Resolve one ball given the bowler's and batter's chosen digits."""
    over_number = innings.legal_balls // BALLS_PER_OVER
    ball_number = (innings.legal_balls % BALLS_PER_OVER) + 1

    is_wide = bowler_digit == "W"
    if is_wide:
        innings.total_runs += 1
        event = BallEvent(
            over_number=over_number,
            ball_number=ball_number,
            bowler_id=innings.current_bowler_id,
            batter_id=innings.current_batter_id,
            runs=1,
            is_wide=True,
        )
        innings.ball_log.append(event)
        # Wide does not consume a legal ball; bowler re-bowls.
        return DeliveryResult(
            event=event, is_wicket=False, is_wide=True, runs_scored=1,
            rotate_strike=False, over_completed=False,
            message="↩️ WIDE BALL — +1 run, re-ball.",
        )

    is_wicket = bowler_digit == batter_digit
    free_hit = innings.free_hit_active

    if is_wicket and free_hit:
        # Free-hit protection: a matching number does NOT count as out.
        # Treat it as a dot ball instead (batter survives).
        is_wicket = False
        runs = 0
        bonus = 0
        msg = "🎁 FREE HIT — delivery matched but wicket voided! Dot ball."
    elif is_wicket:
        innings.wickets += 1
        runs = 0
        bonus = 0
        msg = f"🔴 OUT! {batter_digit} matched the bowler's {bowler_digit}."
    else:
        runs = int(batter_digit)
        bonus = 0
        if powerplay_active and runs in POWERPLAY_TRIGGER_RUNS:
            bonus = POWERPLAY_BONUS_RUNS
            msg = f"🔥 POWERPLAY IMPACT! {runs} runs + {bonus} bonus."
        elif runs == 6:
            msg = "🚀 SIX!"
        elif runs == 4:
            msg = "🏏 FOUR!"
        elif runs == 0:
            msg = "⚫ Dot ball."
        else:
            msg = f"➕ {runs} run(s)."
        innings.total_runs += runs + bonus

    innings.legal_balls += 1
    was_free_hit = innings.free_hit_active
    # A locked pair like 1-6 or 6-1 triggers the NEXT ball as a free hit.
    innings.free_hit_active = _is_free_hit_trigger(bowler_digit, batter_digit)

    event = BallEvent(
        over_number=over_number,
        ball_number=ball_number,
        bowler_id=innings.current_bowler_id,
        batter_id=innings.current_batter_id,
        runs=runs + bonus,
        is_wicket=is_wicket,
        is_free_hit=was_free_hit,
        powerplay_bonus=bonus,
    )
    innings.ball_log.append(event)

    over_completed = innings.legal_balls % BALLS_PER_OVER == 0
    rotate_strike = (not is_wicket) and (runs % 2 == 1)
    if over_completed:
        rotate_strike = not rotate_strike  # end-of-over rotation compounds with odd-run rotation

    return DeliveryResult(
        event=event, is_wicket=is_wicket, is_wide=False, runs_scored=runs + bonus,
        rotate_strike=rotate_strike, over_completed=over_completed, message=msg,
    )


def _is_free_hit_trigger(bowler_digit: str, batter_digit: str) -> bool:
    """A 'locked' delivery — bowler and batter both chose from {1,6} in
    either order (1-6 or 6-1) — grants a free hit on the next ball."""
    pair = {bowler_digit, batter_digit}
    return pair == {"1", "6"}


def compute_target(innings_1_runs: int) -> int:
    return innings_1_runs + 1


def check_innings2_outcome(innings2: InningsState, target: int) -> str | None:
    """Return 'BATTER_WIN', 'BOWLER_WIN', 'DRAW', or None if undecided."""
    if innings2.total_runs >= target:
        return "BATTER_WIN"
    if innings2.wickets >= 1:
        if innings2.total_runs == target - 1:
            return "DRAW"
        return "BOWLER_WIN"
    return None
