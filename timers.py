"""
timers.py — JobQueue-driven timers: per-turn reminder/alert/timeout, and
host-inactivity timeout that opens up captain re-election voting.
"""
from __future__ import annotations

import time

from telegram.ext import ContextTypes

from config import (
    HOST_INACTIVITY_TIMEOUT,
    TIMEOUT_PENALTY_RUNS,
    TURN_FINAL_ALERT_AT,
    TURN_REMINDER_AT,
    TURN_TIMEOUT_AT,
)
from gamestate import GameMode, get_session
from utils import tag_by_id

TURN_JOB_PREFIX = "turn_"
HOST_JOB_PREFIX = "host_"


def _job_name(prefix: str, chat_id: int) -> str:
    return f"{prefix}{chat_id}"


def cancel_turn_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    for job in context.job_queue.get_jobs_by_name(_job_name(TURN_JOB_PREFIX, chat_id)):
        job.schedule_removal()


def schedule_turn_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int, waiting_on_user_id: int) -> None:
    """(Re)start the 60-second turn clock for whoever needs to act next."""
    cancel_turn_timer(context, chat_id)
    context.job_queue.run_once(
        _turn_reminder_tick,
        when=TURN_REMINDER_AT,
        chat_id=chat_id,
        name=_job_name(TURN_JOB_PREFIX, chat_id),
        data={"stage": "reminder", "user_id": waiting_on_user_id, "started_at": time.time()},
    )


async def _turn_reminder_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    session = get_session(chat_id)
    if not session:
        return
    user_id = job.data["user_id"]
    stage = job.data["stage"]

    if stage == "reminder":
        await context.bot.send_message(
            chat_id, f"⏰ {tag_by_id(user_id, str(user_id))}, 30s passed — please play your shot!",
            parse_mode="HTML",
        )
        context.job_queue.run_once(
            _turn_reminder_tick, when=TURN_FINAL_ALERT_AT - TURN_REMINDER_AT,
            chat_id=chat_id, name=_job_name(TURN_JOB_PREFIX, chat_id),
            data={"stage": "final", "user_id": user_id, "started_at": job.data["started_at"]},
        )
    elif stage == "final":
        await context.bot.send_message(
            chat_id, f"🚨 {tag_by_id(user_id, str(user_id))}, 10 seconds left to respond!",
            parse_mode="HTML",
        )
        context.job_queue.run_once(
            _turn_timeout_tick, when=TURN_TIMEOUT_AT - TURN_FINAL_ALERT_AT,
            chat_id=chat_id, name=_job_name(TURN_JOB_PREFIX, chat_id),
            data={"user_id": user_id},
        )


async def _turn_timeout_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Applied when a player fails to act within 60 seconds total."""
    from gamestate import Team  # local import to avoid cycles

    job = context.job
    chat_id = job.chat_id
    session = get_session(chat_id)
    if not session or not session.current_innings:
        return
    innings = session.current_innings
    timed_out_user = job.data["user_id"]

    async with session.lock:
        if session.mode == GameMode.TEAM_MATCH:
            # Opponent team awarded +6 runs.
            innings.total_runs += TIMEOUT_PENALTY_RUNS
            await context.bot.send_message(
                chat_id,
                f"⌛ Timeout! {tag_by_id(timed_out_user, str(timed_out_user))} didn't respond. "
                f"Opponent team awarded +{TIMEOUT_PENALTY_RUNS} runs.",
                parse_mode="HTML",
            )
        else:
            player = session.players.get(timed_out_user)
            if player:
                player.runs = max(0, player.runs - TIMEOUT_PENALTY_RUNS)
            await context.bot.send_message(
                chat_id,
                f"⌛ Timeout! {tag_by_id(timed_out_user, str(timed_out_user))} penalized "
                f"-{TIMEOUT_PENALTY_RUNS} runs for inactivity.",
                parse_mode="HTML",
            )


def cancel_host_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    for job in context.job_queue.get_jobs_by_name(_job_name(HOST_JOB_PREFIX, chat_id)):
        job.schedule_removal()


def schedule_host_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    cancel_host_timer(context, chat_id)
    context.job_queue.run_once(
        _host_timeout_tick, when=HOST_INACTIVITY_TIMEOUT, chat_id=chat_id,
        name=_job_name(HOST_JOB_PREFIX, chat_id),
    )


async def _host_timeout_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    chat_id = context.job.chat_id
    session = get_session(chat_id)
    if not session:
        return
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🗳️ Vote New Host", callback_data="hostvote:open")]]
    )
    await context.bot.send_message(
        chat_id,
        "⚠️ Host has been inactive for 10 minutes. Captains can vote to re-elect a host.",
        reply_markup=keyboard,
    )
