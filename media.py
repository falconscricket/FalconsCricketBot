"""
media.py — Dynamic media asset loader/manager. Owners can bind a
Telegram file_id to gameplay events (FOUR, SIX, DOT, OUT, FREE_HIT,
WIDE, WIN) via /setmedia, and the bot auto-sends that media whenever
the event fires. Persists to media_assets.json.
"""
from __future__ import annotations

import json
import os

from config import MEDIA_ASSETS_PATH, MEDIA_EVENT_KEYS, DATA_DIR

os.makedirs(DATA_DIR, exist_ok=True)


def _load() -> dict[str, str]:
    if not os.path.exists(MEDIA_ASSETS_PATH):
        return {}
    try:
        with open(MEDIA_ASSETS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, str]) -> None:
    with open(MEDIA_ASSETS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def set_media(event_key: str, file_id: str, media_type: str = "photo") -> bool:
    event_key = event_key.upper()
    if event_key not in MEDIA_EVENT_KEYS:
        return False
    data = _load()
    data[event_key] = {"file_id": file_id, "type": media_type}
    _save(data)
    return True


def get_media(event_key: str) -> dict[str, str] | None:
    return _load().get(event_key.upper())


def list_media() -> dict[str, dict[str, str]]:
    return _load()


async def send_event_media(bot, chat_id: int, event_key: str) -> None:
    """Send whatever media the owner has bound to this event, if any.
    Silently does nothing if no media is configured — media is optional,
    never required for the game to function."""
    entry = get_media(event_key)
    if not entry:
        return
    file_id = entry.get("file_id")
    media_type = entry.get("type", "photo")
    if not file_id:
        return
    try:
        if media_type == "animation":
            await bot.send_animation(chat_id, file_id)
        elif media_type == "video":
            await bot.send_video(chat_id, file_id)
        else:
            await bot.send_photo(chat_id, file_id)
    except Exception:
        pass  # never let a bad/expired file_id break the match
