"""
bot.py — Main entry point. Builds the Application, registers every
command/callback handler, and starts polling.
"""
from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from handlers import basic, match, team, tournament
import auction
import host
import owner

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set — copy .env.example to .env and fill it in.")

    app = Application.builder().token(BOT_TOKEN).build()

    # --- Basic / universal commands ---
    app.add_handler(CommandHandler("start", basic.start_cmd))
    app.add_handler(CommandHandler("Feedback", basic.feedback_cmd, filters.ChatType.GROUPS | filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("feedback", basic.feedback_cmd))
    app.add_handler(CommandHandler("score", basic.score_cmd))
    app.add_handler(CommandHandler(["end", "end_match"], basic.end_match_cmd))

    # --- 1v1 match ---
    app.add_handler(CommandHandler("match", match.match_cmd))
    app.add_handler(CallbackQueryHandler(match.join_callback, pattern=r"^m1v1:join$"))

    # --- Solo tournament ---
    app.add_handler(CommandHandler("startgame", tournament.startgame_cmd))
    app.add_handler(CommandHandler("join", tournament.join_cmd))
    app.add_handler(CommandHandler("joingame", tournament.join_cmd))
    app.add_handler(CommandHandler("closelobby", tournament.close_lobby_cmd))
    app.add_handler(CallbackQueryHandler(tournament.tourney_join_callback, pattern=r"^tourney:join$"))
    app.add_handler(CallbackQueryHandler(tournament.over_length_callback, pattern=r"^overlen:"))

    # --- Team match ---
    app.add_handler(CommandHandler("team_match", team.team_match_cmd))
    app.add_handler(CommandHandler("join_a", team.join_team_a))
    app.add_handler(CommandHandler("join_b", team.join_team_b))
    app.add_handler(CommandHandler("add_A", team.add_to_team_cmd))
    app.add_handler(CommandHandler("add_B", team.add_to_team_cmd))
    app.add_handler(CommandHandler("remove_A", team.remove_from_team_cmd))
    app.add_handler(CommandHandler("remove_B", team.remove_from_team_cmd))
    app.add_handler(CallbackQueryHandler(team.team_join_callback, pattern=r"^teamjoin:"))
    app.add_handler(CallbackQueryHandler(host.claim_host, pattern=r"^claimhost$"))

    # --- Host controls ---
    app.add_handler(CommandHandler("host_change", host.host_change))
    app.add_handler(CommandHandler("batting", host.set_batting))
    app.add_handler(CommandHandler("bowling", host.set_bowling))
    app.add_handler(CommandHandler("pp", host.toggle_powerplay))
    app.add_handler(CommandHandler("swap", host.swap_players))

    # --- Auction subsystem ---
    app.add_handler(CommandHandler("add_cap", auction.add_captain))
    app.add_handler(CommandHandler("rm_cap", auction.remove_captain))
    app.add_handler(CommandHandler("cap_change_auction", auction.change_auction_host))
    app.add_handler(CommandHandler("auction_id", auction.set_auction_id))
    app.add_handler(CommandHandler("start_auction", auction.start_auction))
    app.add_handler(CommandHandler("pause_auction", auction.pause_auction))
    app.add_handler(CommandHandler("resume_auction", auction.resume_auction))
    app.add_handler(CommandHandler("auction_host_change", auction.change_auction_host))
    app.add_handler(CommandHandler("xp", auction.place_bid))
    app.add_handler(CommandHandler("unsold", auction.mark_unsold))
    app.add_handler(CommandHandler("sold", auction.sell_current_player))
    app.add_handler(CommandHandler("rm_auction_id", auction.remove_auction))

    # --- Owner-only hidden panel (PM only, filtered inside handlers) ---
    app.add_handler(CommandHandler("setmedia", owner.setmedia_cmd))
    app.add_handler(CommandHandler("listmedia", owner.list_media_cmd))
    app.add_handler(CommandHandler("restart", owner.restart_cmd))

    # --- Plain-text delivery entries — TEXT ONLY, no digit buttons anywhere. ---
    # Batter types 0-6 in the GROUP chat. Each mode's handler checks
    # session.mode itself and no-ops if it doesn't match, so it's safe to
    # register both on the same filter.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, match.group_digit_message)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, tournament.group_digit_message)
    )
    # Bowler types 1-6 or W in PM (0 is always rejected for bowlers).
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, match.pm_bowl_message)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, tournament.pm_bowl_message)
    )

    return app


def main() -> None:
    app = build_application()
    logger.info("Bot starting (polling mode)...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
