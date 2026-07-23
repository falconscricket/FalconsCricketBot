"""
config.py — Central configuration for the Hand Cricket & Auction Bot.
Loads secrets from environment (.env) and defines game-wide constants.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Dual owner support — both IDs get full owner-panel access.
OWNER_IDS: set[int] = set()
for _key in ("OWNER_ID_1", "OWNER_ID_2"):
    _val = os.getenv(_key)
    if _val and _val.isdigit():
        OWNER_IDS.add(int(_val))

# --- Timer constants (seconds) ---
TURN_REMINDER_AT = 30
TURN_FINAL_ALERT_AT = 50
TURN_TIMEOUT_AT = 60
HOST_INACTIVITY_TIMEOUT = 10 * 60  # 10 minutes

# --- Gameplay constants ---
VALID_DIGITS = {"0", "1", "2", "3", "4", "5", "6"}
WIDE_TOKEN = "W"
BALLS_PER_OVER = 6
TIMEOUT_PENALTY_RUNS = 6
POWERPLAY_BONUS_RUNS = 2
POWERPLAY_TRIGGER_RUNS = {4, 5, 6}

# --- Tournament / team match sizes ---
SOLO_TOURNAMENT_MIN_PLAYERS = 4
SOLO_TOURNAMENT_MAX_PLAYERS = 30
TEAM_MATCH_SIZE = 11

# --- Storage paths ---
DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "bot_state.sqlite3")
MEDIA_ASSETS_PATH = os.path.join(DATA_DIR, "media_assets.json")

MEDIA_EVENT_KEYS = {"FOUR", "SIX", "DOT", "OUT", "FREE_HIT", "WIDE", "WIN"}
