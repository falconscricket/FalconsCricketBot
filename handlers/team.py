"""
handlers/team.py — Team Match mode (up to 11v11). Players /join_a or
/join_b; a strict single-team rule blocks joining the opposite team.
A host (claimed or /host_change'd) drives batting/bowling assignment
manually via host.py, and toggles powerplay.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import TEAM_MATCH_SIZE
from database import upsert_player_seen
from gamestate import GameMode, GamePhase, Player, Team, create_session, get_session
from utils import tag, team_join_keyboard


async def team_match_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if get_session(chat_id):
        await update.effective_message.reply_text("⚠️ A match is already active in this chat.")
        return
    session = create_session(chat_id, GameMode.TEAM_MATCH, host_id=None)
    await update.effective_message.reply_text(
        f"🏟️ Team Match started (up to {TEAM_MATCH_SIZE}v{TEAM_MATCH_SIZE}).\n"
        "Claim host, then join Team A or Team B.",
        reply_markup=team_join_keyboard(),
    )


async def join_team_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _join_team(update, context, Team.A)


async def join_team_b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _join_team(update, context, Team.B)


async def _join_team(update: Update, context: ContextTypes.DEFAULT_TYPE, team: Team) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.TEAM_MATCH or session.phase != GamePhase.LOBBY:
        await update.effective_message.reply_text("No open team-match lobby right now.")
        return
    user = update.effective_user
    existing = session.players.get(user.id)

    if existing and existing.team != Team.NONE and existing.team != team:
        other = "A" if team == Team.B else "B"
        await update.effective_message.reply_text(
            f"⚠️ You are already registered in Team {other}."
        )
        return
    if existing and existing.team == team:
        await update.effective_message.reply_text("You're already on this team.")
        return

    roster = session.team_a if team == Team.A else session.team_b
    if len(roster) >= TEAM_MATCH_SIZE:
        await update.effective_message.reply_text(f"⚠️ Team {team.value} is full.")
        return

    session.players[user.id] = Player(user_id=user.id, name=user.first_name, team=team)
    roster.append(user.id)
    upsert_player_seen(user.id, user.first_name)
    await update.effective_message.reply_text(
        f"✅ {tag(user)} joined Team {team.value} ({len(roster)}/{TEAM_MATCH_SIZE}).",
        parse_mode="HTML",
    )


async def team_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the inline 'Join Team A' / 'Join Team B' buttons."""
    query = update.callback_query
    team = Team.A if query.data.endswith(":A") else Team.B
    # Reuse the same logic path as the slash commands.
    class _Fake:
        pass

    fake_update = update
    await _join_team(fake_update, context, team)
    await query.answer()


async def add_to_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_A <user_id> <name> or /add_B — host manually adds a player."""
    await _host_roster_edit(update, context, add=True)


async def remove_from_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _host_roster_edit(update, context, add=False)


async def _host_roster_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, add: bool) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session or session.mode != GameMode.TEAM_MATCH:
        return
    if session.host_id and update.effective_user.id != session.host_id:
        await update.effective_message.reply_text("⚠️ Only the host can edit team rosters.")
        return
    command = update.effective_message.text.split()[0].lower()
    team = Team.A if command.endswith("_a") else Team.B
    roster = session.team_a if team == Team.A else session.team_b

    if not context.args:
        await update.effective_message.reply_text("Usage: /add_A <user_id> [name]  (or /remove_A <user_id>)")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("⚠️ Provide a numeric user ID.")
        return

    if add:
        other_roster = session.team_b if team == Team.A else session.team_a
        if target_id in other_roster:
            await update.effective_message.reply_text("⚠️ That player is already on the other team.")
            return
        name = " ".join(context.args[1:]) or str(target_id)
        if target_id not in roster:
            roster.append(target_id)
        session.players[target_id] = Player(user_id=target_id, name=name, team=team)
        await update.effective_message.reply_text(f"✅ Added {name} to Team {team.value}.")
    else:
        if target_id in roster:
            roster.remove(target_id)
            session.players.pop(target_id, None)
            await update.effective_message.reply_text(f"❌ Removed player from Team {team.value}.")
        else:
            await update.effective_message.reply_text("Player not found on that team.")
