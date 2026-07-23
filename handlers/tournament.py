"""
handlers/tournament.py — Solo Tournament mode (4-30 players). Players
/join a lobby, host (or starter) picks over length (1 or 3 balls per
bowler), then batting order and bowler rotation happen fully
automatically — no host micromanagement required:

  * Batting order strictly follows join order. When a batter gets OUT,
    the next player in join order (who hasn't batted yet and hasn't
    left) is brought in automatically — getting a player out never
    ends the match by itself.
  * Each bowler bowls a fixed spell (`session.over_length` legal balls
    — 1 or 3, chosen at lobby-close). Once their spell is complete,
    the NEXT eligible bowler in join order (skipping the current
    batter and anyone who has left) takes over automatically.
  * Delivery input is typed text only, everywhere — no digit buttons.
    The bowler types 1-6 or W in PM (0 is never accepted from a
    bowler); the batter types 0-6 in the group.
  * The tournament only ends early if eligible players drop below the
    minimum (4). Otherwise it runs until the batting order is
    exhausted, and the winner is decided by the standings (most runs).
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import BALLS_PER_OVER, SOLO_TOURNAMENT_MAX_PLAYERS, SOLO_TOURNAMENT_MIN_PLAYERS
from database import record_match_result, upsert_player_seen
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
from match_engine import evaluate_delivery
from media import send_event_media
from scoreboard import render_innings_scoreboard, render_match_summary
from timers import cancel_turn_timer, schedule_turn_timer
from utils import join_keyboard, overs_length_keyboard, sanitize_batter_input, sanitize_bowler_input, tag, tag_by_id


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


async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if get_session(chat_id):
        await update.effective_message.reply_text("⚠️ A match is already active in this chat.")
        return
    session = create_session(chat_id, GameMode.SOLO_TOURNAMENT, host_id=update.effective_user.id)
    user = update.effective_user
    session.players[user.id] = Player(user_id=user.id, name=user.first_name)
    upsert_player_seen(user.id, user.first_name)
    await update.effective_message.reply_text(
        f"🏆 {tag(user)} started a Solo Tournament! Need {SOLO_TOURNAMENT_MIN_PLAYERS}-"
        f"{SOLO_TOURNAMENT_MAX_PLAYERS} players. Tap to join (or use /join).",
        parse_mode="HTML",
        reply_markup=join_keyboard("tourney"),
    )


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.SOLO_TOURNAMENT or session.phase != GamePhase.LOBBY:
        await update.effective_message.reply_text("No joinable tournament lobby right now. Try /startgame.")
        return
    user = update.effective_user
    if user.id in session.players:
        await update.effective_message.reply_text("You're already in.")
        return
    if len(session.players) >= SOLO_TOURNAMENT_MAX_PLAYERS:
        await update.effective_message.reply_text("Lobby is full.")
        return
    session.players[user.id] = Player(user_id=user.id, name=user.first_name)
    upsert_player_seen(user.id, user.first_name)
    await update.effective_message.reply_text(
        f"✅ {tag(user)} joined ({len(session.players)} players).", parse_mode="HTML"
    )


async def tourney_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.SOLO_TOURNAMENT or session.phase != GamePhase.LOBBY:
        await query.answer("This lobby is no longer open.", show_alert=True)
        return
    user = query.from_user
    if user.id in session.players:
        await query.answer("Already joined.")
        return
    if len(session.players) >= SOLO_TOURNAMENT_MAX_PLAYERS:
        await query.answer("Lobby full.", show_alert=True)
        return
    session.players[user.id] = Player(user_id=user.id, name=user.first_name)
    upsert_player_seen(user.id, user.first_name)
    await query.answer("Joined!")
    await query.message.reply_text(f"✅ {tag(user)} joined ({len(session.players)} players).", parse_mode="HTML")


async def close_lobby_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Host runs this once enough players have joined, to pick over length."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.SOLO_TOURNAMENT:
        return
    if update.effective_user.id != session.host_id:
        await update.effective_message.reply_text("⚠️ Only the tournament starter can close the lobby.")
        return
    if len(session.players) < SOLO_TOURNAMENT_MIN_PLAYERS:
        await update.effective_message.reply_text(
            f"⚠️ Need at least {SOLO_TOURNAMENT_MIN_PLAYERS} players (have {len(session.players)})."
        )
        return
    await update.effective_message.reply_text(
        "Pick balls per bowler spell:", reply_markup=overs_length_keyboard()
    )


async def over_length_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    session = get_session(chat_id)
    if not session:
        await query.answer()
        return
    length = int(query.data.split(":")[1])
    session.over_length = length
    await query.answer(f"Set to {length} ball(s) per bowler.")

    order = list(session.players.keys())
    session.team_a = order  # fixed join-order roster, reused for batting/bowling rotation
    session.tourney_batter_ptr = 0
    session.tourney_bowler_ptr = 1
    batter_id = order[0]
    bowler_id = order[1]
    session.spell_balls = 0
    session.innings_1 = InningsState(
        batting_team=Team.NONE, bowling_team=Team.NONE,
        current_batter_id=batter_id, current_bowler_id=bowler_id,
    )
    session.phase = GamePhase.INNINGS_1

    await query.message.reply_text(
        f"🏏 Tournament begins! {session.players[batter_id].name} bats first, "
        f"{session.players[bowler_id].name} bowls first "
        f"({session.over_length} ball(s) per bowler spell)."
    )
    try:
        await context.bot.send_message(
            bowler_id,
            "🎯 It's your turn to bowl! Type a number <b>1-6</b> or <b>W</b> for wide here in PM.\n"
            "⚠️ 0 is not a valid bowler input.",
            parse_mode="HTML",
        )
        PM_ROUTES[bowler_id] = chat_id
    except Exception:
        await query.message.reply_text(f"⚠️ Couldn't PM {session.players[bowler_id].name}.")
    schedule_turn_timer(context, chat_id, bowler_id)


# --------------------------------------------------------------------
# Automatic rotation engine
# --------------------------------------------------------------------

def _eligible(session) -> list[int]:
    """Players still allowed to take part (haven't left / been removed)."""
    return [uid for uid in session.team_a if uid not in session.left_players]


def _next_batter(session) -> int | None:
    """Next player in strict join order who hasn't batted yet and hasn't
    left. Returns None if the batting order is exhausted."""
    roster = session.team_a
    for idx in range(session.tourney_batter_ptr + 1, len(roster)):
        uid = roster[idx]
        if uid in session.left_players:
            continue
        if session.players[uid].is_out:
            continue
        session.tourney_batter_ptr = idx
        return uid
    return None


def _next_bowler(session, exclude_uid: int) -> int | None:
    """Next eligible bowler in round-robin join order, skipping the
    current batter and anyone who has left. Bowlers may repeat across
    the match (unlike batters, who only get one turn)."""
    roster = session.team_a
    n = len(roster)
    if n == 0:
        return None
    start = session.tourney_bowler_ptr
    for step in range(1, n + 1):
        idx = (start + step) % n
        uid = roster[idx]
        if uid in session.left_players or uid == exclude_uid:
            continue
        session.tourney_bowler_ptr = idx
        return uid
    return None


async def _prompt_bowler(chat_id: int, bowler_id: int, name: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_message(
            bowler_id,
            "🎯 Bowl now! Type 1-6 or W (0 is not allowed for bowlers).",
        )
        PM_ROUTES[bowler_id] = chat_id
    except Exception:
        await context.bot.send_message(chat_id, f"⚠️ Couldn't PM {name}.")
    schedule_turn_timer(context, chat_id, bowler_id)


async def _end_tournament(chat_id: int, session, context: ContextTypes.DEFAULT_TYPE, reason: str) -> None:
    session.phase = GamePhase.FINISHED
    cancel_turn_timer(context, chat_id)
    standings_winner = max(session.players.values(), key=lambda p: p.runs, default=None)
    session.winner = (
        f"{standings_winner.name} wins the tournament with {standings_winner.runs} runs! 🏆"
        if standings_winner else "Tournament ended with no result."
    )
    await context.bot.send_message(chat_id, f"🏁 {reason}", parse_mode="HTML")
    await context.bot.send_message(chat_id, render_match_summary(session), parse_mode="HTML")
    await send_event_media(context.bot, chat_id, "WIN")
    for pid, player in session.players.items():
        record_match_result(
            pid, player.name, player.runs, player.wickets_taken,
            won=bool(standings_winner and pid == standings_winner.user_id),
        )
    end_session(chat_id)


async def _advance_after_wicket(chat_id: int, session, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bring in the next batter (order-wise) after a wicket falls. Getting
    a player out NEVER ends the match on its own — only a genuine
    min-players breach does."""
    if len(_eligible(session)) < SOLO_TOURNAMENT_MIN_PLAYERS:
        await _end_tournament(
            chat_id, session, context,
            f"Tournament auto-ended — fewer than {SOLO_TOURNAMENT_MIN_PLAYERS} eligible players remain."
        )
        return

    next_batter = _next_batter(session)
    if next_batter is None:
        await _end_tournament(chat_id, session, context, "All batters are out — batting order complete!")
        return

    innings = session.current_innings
    innings.current_batter_id = next_batter
    session.spell_balls = 0  # fresh spell context for whoever's bowling to the new batter

    batter = session.players[next_batter]
    bowler = session.players[innings.current_bowler_id]
    await context.bot.send_message(
        chat_id,
        f"🏏 Next up: {tag_by_id(batter.user_id, batter.name)} — "
        f"{tag_by_id(bowler.user_id, bowler.name)} continues bowling.",
        parse_mode="HTML",
    )
    await _prompt_bowler(chat_id, bowler.user_id, bowler.name, context)


async def _rotate_bowler_if_spell_done(chat_id: int, session, context: ContextTypes.DEFAULT_TYPE) -> None:
    """After `session.over_length` legal balls, hand the ball to the next
    eligible bowler in join order (batter is untouched)."""
    if session.spell_balls < session.over_length:
        await _prompt_bowler(
            chat_id, session.current_innings.current_bowler_id,
            session.players[session.current_innings.current_bowler_id].name, context,
        )
        return
    innings = session.current_innings
    next_bowler = _next_bowler(session, exclude_uid=innings.current_batter_id)
    if next_bowler is None:
        # No eligible alternative — same bowler continues their spell.
        session.spell_balls = 0
        await _prompt_bowler(chat_id, innings.current_bowler_id, session.players[innings.current_bowler_id].name, context)
        return
    innings.current_bowler_id = next_bowler
    session.spell_balls = 0
    bowler = session.players[next_bowler]
    await context.bot.send_message(
        chat_id,
        f"🔄 Over complete — {tag_by_id(bowler.user_id, bowler.name)} takes over bowling.",
        parse_mode="HTML",
    )
    await _prompt_bowler(chat_id, next_bowler, bowler.name, context)


async def pm_bowl_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bowler TYPES 1-6 or W in the bot PM. 0 is always rejected here."""
    user_id = update.effective_user.id
    chat_id = PM_ROUTES.get(user_id)
    if chat_id is None:
        return
    session = get_session(chat_id)
    if not session or session.mode != GameMode.SOLO_TOURNAMENT or not session.current_innings:
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
        chat_id, f"🏏 {batter.name}, your turn! Type a number 0-6 in the group.", parse_mode="HTML",
    )
    schedule_turn_timer(context, chat_id, innings.current_batter_id)


async def group_digit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the batter's plain-text digit typed in the group chat, for
    Solo Tournament matches. Advances batting order / bowler spell
    automatically — a wicket never ends the match by itself."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.SOLO_TOURNAMENT or not session.current_innings:
        return
    innings = session.current_innings
    if update.effective_user.id != innings.current_batter_id:
        return
    if innings.pending_bowler_digit is None:
        return

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
                batter.is_out = True
            else:
                batter.runs += result.runs_scored
            bowler.balls_bowled += 1
            session.spell_balls += 1  # only legal balls count toward the spell

        await update.effective_message.reply_text(result.message)
        await send_event_media(context.bot, chat_id, _event_key_for(result))
        await update.effective_message.reply_text(
            render_innings_scoreboard(session, innings, 1), parse_mode="HTML",
        )

        if result.is_wicket:
            await _advance_after_wicket(chat_id, session, context)
            return

        # Same batter continues — hand back to the bowler, rotating the
        # bowler automatically once their spell (over_length balls) is done.
        await _rotate_bowler_if_spell_done(chat_id, session, context)
