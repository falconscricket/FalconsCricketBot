"""
host.py — Host-only controls for Team Matches: claiming host, manual
batting/bowling assignment, swaps, powerplay toggling, and host handover.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from gamestate import Team, get_session
from timers import schedule_host_timer
from utils import tag_by_id


def is_host(session, user_id: int) -> bool:
    return session is not None and session.host_id == user_id


async def claim_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session:
        await update.effective_message.reply_text("No active match in this chat.")
        return
    if session.host_id is not None:
        await update.effective_message.reply_text(
            f"⚠️ Host already assigned: {tag_by_id(session.host_id, str(session.host_id))}",
            parse_mode="HTML",
        )
        return
    session.host_id = update.effective_user.id
    schedule_host_timer(context, chat_id)
    await update.effective_message.reply_text(
        f"👑 {tag_by_id(session.host_id, update.effective_user.first_name)} is now the host.",
        parse_mode="HTML",
    )


async def host_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session:
        return
    if not is_host(session, update.effective_user.id) and update.effective_user.id not in (
        session.host_id,
    ):
        await update.effective_message.reply_text("⚠️ Only the current host can transfer host rights.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /host_change <user_id>")
        return
    try:
        new_host = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("⚠️ Provide a valid numeric user ID.")
        return
    session.host_id = new_host
    schedule_host_timer(context, chat_id)
    await update.effective_message.reply_text(
        f"👑 Host transferred to {tag_by_id(new_host, str(new_host))}.", parse_mode="HTML"
    )


async def set_batting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or not is_host(session, update.effective_user.id):
        await update.effective_message.reply_text("⚠️ Only the host can set the batting player.")
        return
    innings = session.current_innings
    if not innings or not context.args:
        await update.effective_message.reply_text("Usage: /batting <player_no>")
        return
    idx = _resolve_player_index(session, innings.batting_team, context.args[0])
    if idx is None:
        await update.effective_message.reply_text("⚠️ Invalid player number for the batting team.")
        return
    innings.current_batter_id = idx
    session.host_last_action = __import__("time").time()
    await update.effective_message.reply_text(
        f"🏏 {tag_by_id(idx, session.players[idx].name)} is now batting.", parse_mode="HTML"
    )


async def set_bowling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or not is_host(session, update.effective_user.id):
        await update.effective_message.reply_text("⚠️ Only the host can set the bowling player.")
        return
    innings = session.current_innings
    if not innings or not context.args:
        await update.effective_message.reply_text("Usage: /bowling <player_no>")
        return
    idx = _resolve_player_index(session, innings.bowling_team, context.args[0])
    if idx is None:
        await update.effective_message.reply_text("⚠️ Invalid player number for the bowling team.")
        return
    innings.current_bowler_id = idx
    session.host_last_action = __import__("time").time()
    await update.effective_message.reply_text(
        f"🎯 {tag_by_id(idx, session.players[idx].name)} is now bowling.", parse_mode="HTML"
    )


def _resolve_player_index(session, team: Team, arg: str) -> int | None:
    roster = session.team_a if team == Team.A else session.team_b
    try:
        pos = int(arg) - 1
    except ValueError:
        return None
    if 0 <= pos < len(roster):
        return roster[pos]
    return None


async def toggle_powerplay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or not is_host(session, update.effective_user.id):
        await update.effective_message.reply_text("⚠️ Only the host can toggle Powerplay.")
        return
    session.powerplay_active = not session.powerplay_active
    state = "ON 🔥" if session.powerplay_active else "OFF"
    await update.effective_message.reply_text(f"Powerplay is now {state}.")


async def swap_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or not is_host(session, update.effective_user.id):
        await update.effective_message.reply_text("⚠️ Only the host can swap players.")
        return
    innings = session.current_innings
    if not innings:
        await update.effective_message.reply_text("No innings in progress.")
        return
    innings.current_batter_id, innings.non_striker_id = (
        innings.non_striker_id,
        innings.current_batter_id,
    )
    await update.effective_message.reply_text("🔄 Strike swapped.")
