"""
scoreboard.py — Renders a real-time HTML-formatted scoreboard: score,
overs, current run rate, strike rate, ball-by-ball log, and — for
tournaments — Orange Cap (most runs) / Purple Cap (most wickets).
"""
from __future__ import annotations

from gamestate import InningsState, MatchSession
from utils import tag_by_id


def _crr(innings: InningsState) -> float:
    overs_bowled = innings.legal_balls / 6
    if overs_bowled == 0:
        return 0.0
    return round(innings.total_runs / overs_bowled, 2)


def render_innings_scoreboard(session: MatchSession, innings: InningsState, innings_no: int) -> str:
    batter = session.players.get(innings.current_batter_id)
    bowler = session.players.get(innings.current_bowler_id)

    lines = [f"🏏 <b>INNINGS {innings_no}</b>"]
    lines.append(f"Score: <b>{innings.total_runs}/{innings.wickets}</b>  ({innings.overs_display} ov)")
    lines.append(f"CRR: {_crr(innings)}")

    if batter:
        lines.append(
            f"🏃 On strike: {tag_by_id(batter.user_id, batter.name)} "
            f"— {batter.runs} ({batter.balls_faced}b, SR {batter.strike_rate})"
        )
    if bowler:
        lines.append(f"🎯 Bowling: {tag_by_id(bowler.user_id, bowler.name)}")

    if innings.free_hit_active:
        lines.append("🎁 <b>FREE HIT next ball!</b>")

    last_balls = innings.ball_log[-6:]
    if last_balls:
        ball_strs = []
        for b in last_balls:
            if b.is_wide:
                ball_strs.append("Wd")
            elif b.is_wicket:
                ball_strs.append("W")
            else:
                ball_strs.append(str(b.runs))
        lines.append("This over: " + " | ".join(ball_strs))

    if session.target:
        lines.append(f"🎯 TARGET: {session.target} runs")

    return "\n".join(lines)


def render_match_summary(session: MatchSession) -> str:
    lines = ["🏆 <b>MATCH SUMMARY</b>"]
    if session.innings_1:
        lines.append(
            f"Innings 1: {session.innings_1.total_runs}/{session.innings_1.wickets} "
            f"({session.innings_1.overs_display} ov)"
        )
    if session.innings_2:
        lines.append(
            f"Innings 2: {session.innings_2.total_runs}/{session.innings_2.wickets} "
            f"({session.innings_2.overs_display} ov)"
        )
    if session.winner:
        lines.append(f"\n🎉 Result: <b>{session.winner}</b>")

    if len(session.players) > 2:
        orange = max(session.players.values(), key=lambda p: p.runs, default=None)
        purple = max(session.players.values(), key=lambda p: p.wickets_taken, default=None)
        if orange and orange.runs > 0:
            lines.append(f"🟠 Orange Cap: {tag_by_id(orange.user_id, orange.name)} ({orange.runs} runs)")
        if purple and purple.wickets_taken > 0:
            lines.append(
                f"🟣 Purple Cap: {tag_by_id(purple.user_id, purple.name)} ({purple.wickets_taken} wkts)"
            )
    return "\n".join(lines)
