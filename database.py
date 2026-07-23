"""
database.py — Lightweight SQLite persistence for player career stats and
auction logs. Media asset storage is handled separately as JSON (media.py)
since it's a simple flat key -> file_id map that's edited rarely.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from config import DATA_DIR, DB_PATH

os.makedirs(DATA_DIR, exist_ok=True)


def _init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS player_stats (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                matches_played INTEGER DEFAULT 0,
                matches_won INTEGER DEFAULT 0,
                total_runs INTEGER DEFAULT 0,
                total_wickets INTEGER DEFAULT 0,
                highest_score INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS auction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                sold_to_captain_id INTEGER,
                sold_price INTEGER,
                unsold INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_player_seen(user_id: int, name: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO player_stats (user_id, name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name=excluded.name
            """,
            (user_id, name),
        )


def record_match_result(user_id: int, name: str, runs: int, wickets: int, won: bool) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO player_stats (user_id, name, matches_played, matches_won,
                total_runs, total_wickets, highest_score)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                matches_played = matches_played + 1,
                matches_won = matches_won + excluded.matches_won,
                total_runs = total_runs + excluded.total_runs,
                total_wickets = total_wickets + excluded.total_wickets,
                highest_score = MAX(highest_score, excluded.highest_score)
            """,
            (user_id, name, int(won), runs, wickets, runs),
        )


def get_player_stats(user_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM player_stats WHERE user_id = ?", (user_id,))
        return cur.fetchone()


def log_auction_result(auction_id: str, chat_id: int, player_id: int, player_name: str,
                        sold_to_captain_id: int | None, sold_price: int | None,
                        unsold: bool) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auction_log
                (auction_id, chat_id, player_id, player_name, sold_to_captain_id, sold_price, unsold)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (auction_id, chat_id, player_id, player_name, sold_to_captain_id, sold_price, int(unsold)),
        )


def get_auction_log(auction_id: str) -> list[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM auction_log WHERE auction_id = ? ORDER BY id", (auction_id,)
        )
        return cur.fetchall()


_init_db()
