"""
handlers/match.py — The 1v1 Normal Match flow:
join -> coin toss -> innings 1 (bowler picks in PM, batter picks in
group) -> target announced -> innings 2 -> result.
"""
from __future__ import annotations

import random

from telegram import Update
from telegram.ext import ContextTypes

from database import record_match_result, upsert_player_seen
from media import send_event_media
from gamestate import (
    GameMode,
    GamePhase,
    InningsState,
    PM_ROUTES,
    Player,
    Team,
    create_session,
    end_session,
    get_session,
)
from match_engine import check_innings2_outcome, compute_target, evaluate_delivery
from scoreboard import render_innings_scoreboard, render_match_summary
from timers import cancel_turn_timer, schedule_turn_timer
from utils import join_keyboard, sanitize_batter_input, sanitize_bowler_input, tag


def _event_key_for(result) -> str:
    """Map a resolved delivery to the media event key it corresponds to."""
    if result.event.is_free_hit:
        return "FREE_HIT"
    if result.is_wide:
        return "WIDE"
    if result.is_wicket:
        return "OUT"
    if result.runs_scored == 6:
        return "SIX"
    if result.runs_scored == 4:
        return "FOUR"
    return "DOT"


async def match_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if get_session(chat_id):
        await update.effective_message.reply_text("⚠️ A match is already active in this chat. /end_match first.")
        return
    session = create_session(chat_id, GameMode.ONE_V_ONE, host_id=None)
    user = update.effective_user
    session.players[user.id] = Player(user_id=user.id, name=user.first_name)
    upsert_player_seen(user.id, user.first_name)
    await update.effective_message.reply_text(
        f"🏏 {tag(user)} started a 1v1 match! Tap below to join.",
        parse_mode="HTML",
        reply_markup=join_keyboard("m1v1"),
    )


async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.ONE_V_ONE or session.phase != GamePhase.LOBBY:
        await query.answer("This match can no longer be joined.", show_alert=True)
        return
    user = query.from_user
    if user.id in session.players:
        await query.answer("You're already in this match.")
        return
    if len(session.players) >= 2:
        await query.answer("Match is already full.", show_alert=True)
        return
    session.players[user.id] = Player(user_id=user.id, name=user.first_name)
    upsert_player_seen(user.id, user.first_name)
    await query.answer("Joined!")
    await query.message.reply_text(f"✅ {tag(user)} joined the match!", parse_mode="HTML")

    if len(session.players) == 2:
        await _do_toss(query.message.chat, session, context)


async def _do_toss(chat, session, context: ContextTypes.DEFAULT_TYPE) -> None:
    session.phase = GamePhase.TOSS
    ids = list(session.players.keys())
    random.shuffle(ids)
    batter_id, bowler_id = ids[0], ids[1]
    session.players[batter_id].team = Team.NONE
    session.innings_1 = InningsState(
        batting_team=Team.NONE, bowling_team=Team.NONE,
        current_batter_id=batter_id, current_bowler_id=bowler_id,
    )
    session.phase = GamePhase.INNINGS_1

    batter = session.players[batter_id]
    bowler = session.players[bowler_id]
    await context.bot.send_message(
        chat.id,
        f"🪙 Toss result: {batter.name} bats first, {bowler.name} bowls first!\n\n"
        f"🎯 {bowler.name}, check your PM to bowl the first ball.",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            bowler_id,
            "🎯 It's your turn to bowl! Type a number <b>1-6</b> or <b>W</b> for wide here in PM.\n"
            "⚠️ 0 is not a valid bowler input.",
            parse_mode="HTML",
        )
        PM_ROUTES[bowler_id] = chat.id
    except Exception:
        await context.bot.send_message(
            chat.id, f"⚠️ Couldn't PM {bowler.name} — ask them to start the bot in PM first."
        )
    schedule_turn_timer(context, chat.id, bowler_id)


async def pm_bowl_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bowler TYPES their delivery (1-6 or W) directly in the bot PM.
    No inline buttons are shown for this — text input only. This handler
    only acts on 1v1 matches; Solo Tournament PM input is handled in
    handlers/tournament.py."""
    user_id = update.effective_user.id
    chat_id = PM_ROUTES.get(user_id)
    if chat_id is None:
        return
    session = get_session(chat_id)
    if not session or session.mode != GameMode.ONE_V_ONE or not session.current_innings:
        return
    innings = session.current_innings
    if user_id != innings.current_bowler_id:
        return
    if innings.pending_bowler_digit is not None:
        await update.effective_message.reply_text("Delivery already locked for this ball.")
        return

    digit = sanitize_bowler_input(update.effective_message.text)
    if digit is None:
        if (update.effective_message.text or "").strip() == "0":
            await update.effective_message.reply_text("⚠️ Bowlers can't play 0. Enter 1-6 or W.")
        else:
            await update.effective_message.reply_text("⚠️ Please enter a number between 1 and 6, or W for wide.")
        return

    innings.pending_bowler_digit = digit
    await update.effective_message.reply_text("✅ Delivery Locked")

    batter = session.players[innings.current_batter_id]
    await context.bot.send_message(
        chat_id,
        f"🏏 {batter.name}, your turn! Type a number 0-6 in the group.",
        parse_mode="HTML",
    )
    schedule_turn_timer(context, chat_id, innings.current_batter_id)


async def group_digit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the batter's plain-text digit typed directly in the group chat."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.ONE_V_ONE or not session.current_innings:
        return
    innings = session.current_innings
    if update.effective_user.id != innings.current_batter_id:
        return
    if innings.pending_bowler_digit is None:
        return  # bowler hasn't locked a delivery yet

    digit = sanitize_batter_input(update.effective_message.text)
    if digit is None:
        await update.effective_message.reply_text("Please type just a single number from 0 to 6 (no other text).")
        return

    async with session.lock:
        bowler_digit = innings.pending_bowler_digit
        innings.pending_bowler_digit = None
        cancel_turn_timer(context, chat_id)

        result = evaluate_delivery(innings, bowler_digit, digit, session.powerplay_active)
        batter = session.players[innings.current_batter_id]
        bowler = session.players[innings.current_bowler_id]

        if not result.is_wide:
            batter.balls_faced += 1
            if result.is_wicket:
                bowler.wickets_taken += 1
            else:
                batter.runs += result.runs_scored
            bowler.balls_bowled += 1

        await update.effective_message.reply_text(result.message)
        await send_event_media(context.bot, chat_id, _event_key_for(result))
        await update.effective_message.reply_text(
            render_innings_scoreboard(session, innings, 1 if session.phase == GamePhase.INNINGS_1 else 2),
            parse_mode="HTML",
        )

        if session.phase == GamePhase.INNINGS_1:
            if result.is_wicket:
                await _start_innings_2(update.effective_chat, session, context)
                return
        else:
            outcome = check_innings2_outcome(innings, session.target)
            if outcome:
                await _finish_match(update.effective_chat, session, context, outcome)
                return

        # Continue same innings — bowler bowls again.
        try:
            await context.bot.send_message(
                bowler.user_id,
                "🎯 Bowl again! Type 1-6 or W (0 is not allowed for bowlers).",
            )
        except Exception:
            await context.bot.send_message(chat_id, f"⚠️ Couldn't PM {bowler.name}.")
        schedule_turn_timer(context, chat_id, bowler.user_id)


async def _start_innings_2(chat, session, context: ContextTypes.DEFAULT_TYPE) -> None:
    session.phase = GamePhase.INNINGS_BREAK
    innings1 = session.innings_1
    session.target = compute_target(innings1.total_runs)

    old_batter_id = innings1.current_batter_id
    old_bowler_id = innings1.current_bowler_id
    # Roles flip for innings 2.
    session.innings_2 = InningsState(
        batting_team=Team.NONE, bowling_team=Team.NONE,
        current_batter_id=old_bowler_id, current_bowler_id=old_batter_id,
    )
    session.phase = GamePhase.INNINGS_2

    await context.bot.send_message(
        chat.id,
        f"🎯 <b>TARGET: {session.target} Runs</b>\n\nInnings 2 begins!",
        parse_mode="HTML",
    )
    bowler = session.players[old_batter_id]
    try:
        await context.bot.send_message(
            bowler.user_id,
            "🎯 Bowl the first ball of innings 2! Type 1-6 or W (0 is not allowed for bowlers).",
        )
        PM_ROUTES[bowler.user_id] = chat.id
    except Exception:
        await context.bot.send_message(chat.id, f"⚠️ Couldn't PM {bowler.name}.")
    schedule_turn_timer(context, chat.id, bowler.user_id)


async def _finish_match(chat, session, context: ContextTypes.DEFAULT_TYPE, outcome: str) -> None:
    session.phase = GamePhase.FINISHED
    cancel_turn_timer(context, chat.id)

    batter_id = session.innings_2.current_batter_id
    bowler_id = session.innings_2.current_bowler_id
    batter = session.players[batter_id]
    bowler = session.players[bowler_id]

    if outcome == "BATTER_WIN":
        session.winner = f"{batter.name} wins by chasing the target! 🏆"
        winner_id, loser_id = batter_id, bowler_id
    elif outcome == "BOWLER_WIN":
        session.winner = f"{bowler.name} wins by defending the target! 🏆"
        winner_id, loser_id = bowler_id, batter_id
    else:
        session.winner = "It's a DRAW — out at target minus 1! 🤝"
        winner_id, loser_id = None, None

    await context.bot.send_message(chat.id, render_match_summary(session), parse_mode="HTML")
    await send_event_media(context.bot, chat.id, "WIN")

    for pid, player in session.players.items():
        record_match_result(pid, player.name, player.runs, player.wickets_taken, won=(pid == winner_id))

    end_session(chat.id)
