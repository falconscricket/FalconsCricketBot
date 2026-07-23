"""
auction.py — Full player-auction engine: captain registration, purses,
live bidding, unsold pool tracking, and pause/resume/host-change controls.
Each auction is keyed by an auction_id so a chat can run multiple auctions
over time (results stay logged in the database against that ID).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from telegram import Update
from telegram.ext import ContextTypes

from database import log_auction_result
from utils import tag_by_id

DEFAULT_PURSE = 1000


@dataclass
class Captain:
    user_id: int
    name: str
    purse: int = DEFAULT_PURSE
    squad: list[int] = field(default_factory=list)


@dataclass
class AuctionPlayer:
    user_id: int
    name: str
    base_price: int = 20


@dataclass
class AuctionState:
    auction_id: str
    chat_id: int
    host_id: int
    captains: dict[int, Captain] = field(default_factory=dict)
    pool: list[AuctionPlayer] = field(default_factory=list)
    unsold: list[AuctionPlayer] = field(default_factory=list)
    current_player: AuctionPlayer | None = None
    current_bid: int = 0
    current_bidder_id: int | None = None
    paused: bool = False
    active: bool = False


# chat_id -> AuctionState (one live auction per chat)
AUCTIONS: dict[int, AuctionState] = {}


def get_auction(chat_id: int) -> AuctionState | None:
    return AUCTIONS.get(chat_id)


async def add_captain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auction = AUCTIONS.setdefault(
        chat_id, AuctionState(auction_id=f"AUC{chat_id}", chat_id=chat_id, host_id=update.effective_user.id)
    )
    if not context.args:
        await update.effective_message.reply_text("Usage: /add_cap <user_id> <name>")
        return
    cap_id = int(context.args[0])
    name = " ".join(context.args[1:]) or str(cap_id)
    auction.captains[cap_id] = Captain(user_id=cap_id, name=name)
    await update.effective_message.reply_text(
        f"👑 Captain added: {tag_by_id(cap_id, name)} (purse: {DEFAULT_PURSE})", parse_mode="HTML"
    )


async def remove_captain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction or not context.args:
        await update.effective_message.reply_text("Usage: /rm_cap <user_id>")
        return
    cap_id = int(context.args[0])
    auction.captains.pop(cap_id, None)
    await update.effective_message.reply_text("Captain removed.")


async def change_auction_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction or not context.args:
        await update.effective_message.reply_text("Usage: /auction_host_change <user_id>")
        return
    auction.host_id = int(context.args[0])
    await update.effective_message.reply_text("Auction host updated.")


async def set_auction_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction or not context.args:
        await update.effective_message.reply_text("Usage: /auction_id <id>")
        return
    auction.auction_id = context.args[0]
    await update.effective_message.reply_text(f"Auction ID set to {auction.auction_id}.")


async def start_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction:
        await update.effective_message.reply_text("Set up captains first with /add_cap.")
        return
    if not auction.captains:
        await update.effective_message.reply_text("⚠️ Add at least one captain before starting.")
        return
    auction.active = True
    auction.paused = False
    await update.effective_message.reply_text(
        f"🎪 Auction <b>{auction.auction_id}</b> started with {len(auction.captains)} captain(s)!",
        parse_mode="HTML",
    )


async def pause_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auction = get_auction(update.effective_chat.id)
    if auction:
        auction.paused = True
        await update.effective_message.reply_text("⏸️ Auction paused.")


async def resume_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auction = get_auction(update.effective_chat.id)
    if auction:
        auction.paused = False
        await update.effective_message.reply_text("▶️ Auction resumed.")


async def place_bid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/xp <amount> — captain raises the current bid by/to <amount>."""
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction or not auction.active or auction.paused:
        await update.effective_message.reply_text("No live auction to bid on right now.")
        return
    cap = auction.captains.get(update.effective_user.id)
    if not cap:
        await update.effective_message.reply_text("⚠️ Only registered captains can bid.")
        return
    if not auction.current_player:
        await update.effective_message.reply_text("⚠️ No player currently up for bidding.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /xp <bid_amount>")
        return
    amount = int(context.args[0])
    if amount <= auction.current_bid:
        await update.effective_message.reply_text(f"⚠️ Bid must exceed current bid of {auction.current_bid}.")
        return
    if amount > cap.purse:
        await update.effective_message.reply_text("⚠️ Bid exceeds your remaining purse.")
        return
    auction.current_bid = amount
    auction.current_bidder_id = cap.user_id
    await update.effective_message.reply_text(
        f"💰 {tag_by_id(cap.user_id, cap.name)} bids {amount} for {auction.current_player.name}.",
        parse_mode="HTML",
    )


async def mark_unsold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction or not auction.current_player:
        await update.effective_message.reply_text("No player currently up for bidding.")
        return
    player = auction.current_player
    auction.unsold.append(player)
    log_auction_result(auction.auction_id, chat_id, player.user_id, player.name, None, None, unsold=True)
    await update.effective_message.reply_text(f"❌ {player.name} went UNSOLD.")
    auction.current_player = None
    auction.current_bid = 0
    auction.current_bidder_id = None


async def sell_current_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sold — host confirms the sale to the current highest bidder."""
    chat_id = update.effective_chat.id
    auction = get_auction(chat_id)
    if not auction or not auction.current_player or not auction.current_bidder_id:
        await update.effective_message.reply_text("No active bid to finalize.")
        return
    player = auction.current_player
    cap = auction.captains[auction.current_bidder_id]
    cap.purse -= auction.current_bid
    cap.squad.append(player.user_id)
    log_auction_result(
        auction.auction_id, chat_id, player.user_id, player.name,
        cap.user_id, auction.current_bid, unsold=False,
    )
    await update.effective_message.reply_text(
        f"✅ SOLD! {player.name} → {tag_by_id(cap.user_id, cap.name)} for {auction.current_bid}.",
        parse_mode="HTML",
    )
    auction.current_player = None
    auction.current_bid = 0
    auction.current_bidder_id = None


async def remove_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.effective_message.reply_text("Usage: /rm_auction_id <id>")
        return
    auction = get_auction(chat_id)
    if auction and auction.auction_id == context.args[0]:
        AUCTIONS.pop(chat_id, None)
        await update.effective_message.reply_text("Auction removed.")
    else:
        await update.effective_message.reply_text("No matching auction found in this chat.")
