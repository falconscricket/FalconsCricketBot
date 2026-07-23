"""
owner.py — Hidden owner-only commands. Only usable in a private message
(PM) with the bot, and only by a user ID listed in config.OWNER_IDS.
These commands are intentionally excluded from any public command menu.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import MEDIA_EVENT_KEYS, OWNER_IDS
from media import list_media, set_media


def _is_owner_pm(update: Update) -> bool:
    return (
        update.effective_chat.type == "private"
        and update.effective_user is not None
        and update.effective_user.id in OWNER_IDS
    )


# What each event key means, and when it fires during a match — shown to
# the owner so they know exactly what they're setting media for.
_EVENT_DESCRIPTIONS = {
    "FOUR": "Sent whenever a batter scores a 4.",
    "SIX": "Sent whenever a batter scores a 6.",
    "DOT": "Sent on a dot ball (0 runs, not out).",
    "OUT": "Sent whenever a batter gets out.",
    "FREE_HIT": "Sent when a free-hit delivery is triggered (locked 1-6 / 6-1).",
    "WIDE": "Sent on every wide ball.",
    "WIN": "Sent when a match/tournament ends and a winner is declared.",
}


async def setmedia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner_pm(update):
        return  # silently ignore — command doesn't exist for non-owners
    if len(context.args) < 1:
        lines = ["🎛 <b>Set media per event</b> — each event below can be set separately:\n"]
        for key in sorted(MEDIA_EVENT_KEYS):
            desc = _EVENT_DESCRIPTIONS.get(key, "")
            lines.append(f"• <b>{key}</b> — {desc}")
        lines.append(
            "\nUsage: reply to (or attach) a photo/GIF/video with:\n"
            "<code>/setmedia SIX</code>\n"
            "Or pass a raw file_id directly:\n"
            "<code>/setmedia SIX &lt;file_id&gt;</code>\n\n"
            "Use /listmedia to see what's currently set for each event."
        )
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        return
    event_key = context.args[0].upper()
    if event_key not in MEDIA_EVENT_KEYS:
        await update.effective_message.reply_text(
            f"⚠️ Unknown event key '{event_key}'. Valid keys: {', '.join(sorted(MEDIA_EVENT_KEYS))}"
        )
        return

    file_id = None
    media_type = "photo"
    msg = update.effective_message
    source = msg.reply_to_message if msg.reply_to_message else msg
    if source.photo:
        file_id = source.photo[-1].file_id
        media_type = "photo"
    elif source.animation:
        file_id = source.animation.file_id
        media_type = "animation"
    elif source.video:
        file_id = source.video.file_id
        media_type = "video"
    elif len(context.args) >= 2:
        file_id = context.args[1]
        media_type = "photo"

    if not file_id:
        await update.effective_message.reply_text(
            "⚠️ Attach/reply to a photo, GIF, or video, or pass a raw file_id as the 2nd argument."
        )
        return

    if set_media(event_key, file_id, media_type):
        await update.effective_message.reply_text(
            f"✅ Media for <b>{event_key}</b> updated ({media_type}). "
            f"It'll now be sent automatically whenever that event fires in any match.",
            parse_mode="HTML",
        )
    else:
        await update.effective_message.reply_text(
            f"⚠️ Unknown event key. Valid keys: {', '.join(sorted(MEDIA_EVENT_KEYS))}"
        )


async def list_media_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner_pm(update):
        return
    data = list_media()
    lines = ["🎛 <b>Media set per event:</b>\n"]
    for key in sorted(MEDIA_EVENT_KEYS):
        entry = data.get(key)
        if entry:
            lines.append(f"• <b>{key}</b> — set ({entry.get('type', 'photo')})")
        else:
            lines.append(f"• <b>{key}</b> — <i>not set</i>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner_pm(update):
        return
    await update.effective_message.reply_text("♻️ Restarting bot process...")
    import os
    import sys

    os.execv(sys.executable, [sys.executable] + sys.argv)
