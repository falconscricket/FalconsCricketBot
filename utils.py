"""
utils.py — Shared helpers: HTML-safe formatting, user tagging, input
sanitization, and inline-keyboard builders used across handlers.
"""
from __future__ import annotations

from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, User


def tag(user: User) -> str:
    """Return an HTML mention tag for a Telegram user."""
    name = escape(user.first_name or user.username or str(user.id))
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def tag_by_id(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def sanitize_batter_input(text: str) -> str | None:
    """Return '0'-'6' if valid for a BATTER, else None. Batters may play 0."""
    if text is None:
        return None
    cleaned = text.strip().upper()
    if cleaned in {"0", "1", "2", "3", "4", "5", "6"}:
        return cleaned
    return None


def sanitize_bowler_input(text: str) -> str | None:
    """Return '1'-'6' or 'W' if valid for a BOWLER, else None.
    NOTE: '0' is deliberately excluded here — a bowler is never allowed
    to bowl a 0. Only the batter can ever enter 0 (see sanitize_batter_input).
    """
    if text is None:
        return None
    cleaned = text.strip().upper()
    if cleaned in {"1", "2", "3", "4", "5", "6", "W"}:
        return cleaned
    return None


def bowl_now_keyboard(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=bowl_{chat_id}"
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎯 Bowl Now", url=url)]])


def back_to_group_keyboard(group_chat_id: int, group_username: str | None = None) -> InlineKeyboardMarkup:
    """PM button shown right after a delivery locks, guiding the bowler
    back to the group to watch the batter's response. No digit buttons —
    delivery input is typed text only, everywhere."""
    if group_username:
        url = f"https://t.me/{group_username}"
    else:
        # Private/basic groups without a public @username can't be deep-linked
        # directly — fall back to a no-op-safe placeholder link to t.me/share
        # so the button still renders without crashing.
        url = "https://t.me/"
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Go to Group Chat", url=url)]])


def join_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Join Match", callback_data=f"{callback_prefix}:join")]]
    )


def team_join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🅰️ Join Team A", callback_data="teamjoin:A"),
                InlineKeyboardButton("🅱️ Join Team B", callback_data="teamjoin:B"),
            ],
            [InlineKeyboardButton("🙋 I'm Host", callback_data="claimhost")],
        ]
    )


def overs_length_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("1 Ball / Bowler", callback_data="overlen:1"),
                InlineKeyboardButton("3 Balls / Bowler", callback_data="overlen:3"),
            ]
        ]
    )
