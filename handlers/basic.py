"""
handlers/basic.py — /start, /Feedback, /score, /end, /end_match and the
deep-link entry point used when a bowler taps "🎯 Bowl Now" in PM.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from gamestate import PM_ROUTES, end_session, get_session
from scoreboard import render_innings_scoreboard, render_match_summary


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if args and args[0].startswith("bowl_"):
        try:
            chat_id = int(args[0].split("_", 1)[1])
        except (IndexError, ValueError):
            chat_id = None
        if chat_id:
            PM_ROUTES[update.effective_user.id] = chat_id
            await update.effective_message.reply_text(
                "🎯 Enter your delivery: a single digit 0-6 (or 'W' for wide if host mode)."
            )
            return

    await update.effective_message.reply_text(
        "🏏 <b>Hand Cricket Bot</b>\n\n"
        "Commands:\n"
        "/match — start a 1v1 match\n"
        "/startgame — start a solo tournament (4-30 players)\n"
        "/join — join the group match\n"
        "/join_a /join_b — join Team A/B for a full team match\n"
        "/score — show live scoreboard\n"
        "/end_match — end the current match\n"
        "/Feedback <text> — send feedback to the developers",
        parse_mode="HTML",
    )


async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else None
    if not text:
        await update.effective_message.reply_text("Usage: /Feedback <your message>")
        return
    from config import OWNER_IDS

    for owner_id in OWNER_IDS:
        try:
            await context.bot.send_message(
                owner_id,
                f"📩 Feedback from {update.effective_user.id} "
                f"(@{update.effective_user.username}):\n{text}",
            )
        except Exception:
            pass
    await update.effective_message.reply_text("✅ Thanks! Your feedback has been sent.")


async def score_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_session(update.effective_chat.id)
    if not session or not session.current_innings:
        await update.effective_message.reply_text("No match is currently in progress here.")
        return
    innings_no = 1 if session.phase.name == "INNINGS_1" else 2
    text = render_innings_scoreboard(session, session.current_innings, innings_no)
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def end_match_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session:
        await update.effective_message.reply_text("No active match to end.")
        return
    if session.host_id and update.effective_user.id != session.host_id:
        await update.effective_message.reply_text("⚠️ Only the host can end this match.")
        return
    summary = render_match_summary(session)
    end_session(chat_id)
    await update.effective_message.reply_text(
        "🛑 Match ended.\n\n" + summary, parse_mode="HTML"
    )
