#!/usr/bin/env python3
"""
Mock test using REAL trade snapshots with configurable filters.

Usage:
    uv run python test_real_mock.py [--interval 15] [--min-usd 1]
"""

import asyncio
import argparse
import random
from telegram import Bot

from src.config import TELEGRAM_BOT_TOKEN, logger
from src.storage.database import db
from src.storage.models import Trade, EnrichedTrade, Market
from src.bot.messages import format_trade_alert
from src.api.gamma import gamma_client

# ============================================================
# REAL TRADE SNAPSHOTS (from ENVIO)
# ============================================================
REAL_TRADES = [
    {
        "id": "0x0b5ce17482ab27371e74564dba09fb9b278e0d471401479b19a6b8332d8c50ab-1079",
        "order_hash": "0x5691d09fa899bcb1d793e7530ba411faaecee9de8e288f462c7e248788750a02",
        "maker": "0xe6263967a04a467a9f2125653f3763338bb3d6c0",
        "taker": "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
        "maker_asset_id": "0",
        "taker_asset_id": "67771592658734375826482480707066342094478791361226472999610240778201021673014",
        "maker_amount_filled": 999999,
        "taker_amount_filled": 1219511,
        "timestamp": 1767693251,
        "tx_hash": "0x0b5ce17482ab27371e74564dba09fb9b278e0d471401479b19a6b8332d8c50ab",
        "log_index": 1079,
    },
    {
        "id": "0xffba5c5455246669d608da1e7d72ebba8343634f902b44f76c3778f644d6b4ac-1051",
        "order_hash": "0x29e5f9391c0c7a5ad25a111e81682f1f7fae13a815982a75202b2e150bd9b761",
        "maker": "0x7aab2a99cdaa69ad938309fbb12b073d7ef8685d",
        "taker": "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
        "maker_asset_id": "86235967108151215463418486150013487760758658156938775714487299383837708229050",
        "taker_asset_id": "0",
        "maker_amount_filled": 13870000,
        "taker_amount_filled": 5964100,
        "timestamp": 1767693251,
        "tx_hash": "0xffba5c5455246669d608da1e7d72ebba8343634f902b44f76c3778f644d6b4ac",
        "log_index": 1051,
    },
    {
        "id": "0x30862631c487363b6b081e9a3d8e72e90d82d767d49c7b3bd9861626929eb8d9-897",
        "order_hash": "0x52e64a623238a1a119bf87d774a8ae1a6bacf0ec81170e758f373a3c01b22bff",
        "maker": "0x724db3c436dcc7b26fbe1ae0c0d6af538b588dea",
        "taker": "0x206181ab4e7f7572a9ac630c323cc829e4e73400",
        "maker_asset_id": "0",
        "taker_asset_id": "9094997789834132566062146970526442476010753575113096619530619484156568834622",
        "maker_amount_filled": 46992000,
        "taker_amount_filled": 48000000,
        "timestamp": 1767693251,
        "tx_hash": "0x30862631c487363b6b081e9a3d8e72e90d82d767d49c7b3bd9861626929eb8d9",
        "log_index": 897,
    },
    {
        "id": "0xf5e863d7077f93e2483e204bc794a768079f295d9dcf63cff47c7c0d600822e9-960",
        "order_hash": "0xe204f74785e0e8a4e220ac424d3fade37ae32784f31d0f1597d8767a33a1a7c8",
        "maker": "0x5f6aedef4812ce1ca8773949bdfdb00b480faba2",
        "taker": "0x153fd6063a9105ddb1aa00fbe06c740053243423",
        "maker_asset_id": "0",
        "taker_asset_id": "38794857129189519302913732527438547171034236284146476803449154191391201203132",
        "maker_amount_filled": 8491200,
        "taker_amount_filled": 9760000,
        "timestamp": 1767693251,
        "tx_hash": "0xf5e863d7077f93e2483e204bc794a768079f295d9dcf63cff47c7c0d600822e9",
        "log_index": 960,
    },
    {
        "id": "0xb3313ea3be90073d7459e2d51b5d17d3b975bf343329c297279cf6c371365d37-362",
        "order_hash": "0x2f2bff8b5e320041d5bd7d50624d8e7a4dfc976b4e29964e7f5bbe792f6665e9",
        "maker": "0xdbe3bfbbe71887563a7a66308fff5ec359dac15b",
        "taker": "0x589222a5124a96765443b97a3498d89ffd824ad2",
        "maker_asset_id": "0",
        "taker_asset_id": "67771592658734375826482480707066342094478791361226472999610240778201021673014",
        "maker_amount_filled": 5491800,
        "taker_amount_filled": 6780000,
        "timestamp": 1767693251,
        "tx_hash": "0xb3313ea3be90073d7459e2d51b5d17d3b975bf343329c297279cf6c371365d37",
        "log_index": 362,
    },
]

# Mock market data (since we can't always fetch from Gamma)
MOCK_MARKETS = {
    "67771592658734375826482480707066342094478791361226472999610240778201021673014": Market(
        condition_id="0x1",
        question="Will Bitcoin reach $100,000 by March 2025?",
        slug="bitcoin-100k-march-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.82", "0.18"],
        clob_token_ids=["67771592658734375826482480707066342094478791361226472999610240778201021673014", "35586720288583621720023981411258596098385057107725043660877833279964408336159"],
        category="Crypto",
    ),
    "86235967108151215463418486150013487760758658156938775714487299383837708229050": Market(
        condition_id="0x2",
        question="Will ETH reach $5,000 in Q1 2025?",
        slug="eth-5000-q1-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.43", "0.57"],
        clob_token_ids=["86235967108151215463418486150013487760758658156938775714487299383837708229050", "36871185811494917837290631270967949339802924836522156631903491865481159565412"],
        category="Crypto",
    ),
    "9094997789834132566062146970526442476010753575113096619530619484156568834622": Market(
        condition_id="0x3",
        question="Will Trump be inaugurated on January 20?",
        slug="trump-inauguration-jan-20",
        outcomes=["Yes", "No"],
        outcome_prices=["0.98", "0.02"],
        clob_token_ids=["9094997789834132566062146970526442476010753575113096619530619484156568834622", "38384431304777478675443030058599948989915447983523020662966395710844987521858"],
        category="Politics",
    ),
    "38794857129189519302913732527438547171034236284146476803449154191391201203132": Market(
        condition_id="0x4",
        question="Will Fed cut rates in January 2025?",
        slug="fed-rate-cut-jan-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.12", "0.88"],
        clob_token_ids=["38794857129189519302913732527438547171034236284146476803449154191391201203132", "113252574487744213559868711279150753275851055822813867867814092997503018559308"],
        category="Economics",
    ),
}


def parse_trade(data: dict) -> Trade:
    """Parse trade data dict into Trade object."""
    return Trade(
        id=data["id"],
        order_hash=data["order_hash"],
        maker=data["maker"].lower(),
        taker=data["taker"].lower(),
        maker_asset_id=data["maker_asset_id"],
        taker_asset_id=data["taker_asset_id"],
        maker_amount_filled=data["maker_amount_filled"],
        taker_amount_filled=data["taker_amount_filled"],
        timestamp=data["timestamp"],
        tx_hash=data["tx_hash"],
        log_index=data["log_index"],
    )


def get_market_for_trade(trade: Trade) -> tuple[Market | None, str | None]:
    """Get market and outcome for a trade."""
    token_id = trade.outcome_token_id

    if token_id in MOCK_MARKETS:
        market = MOCK_MARKETS[token_id]
        try:
            idx = market.clob_token_ids.index(token_id)
            outcome = market.outcomes[idx]
        except (ValueError, IndexError):
            outcome = "Yes"
        return market, outcome

    # Try other token IDs
    for tid, market in MOCK_MARKETS.items():
        if tid in [trade.maker_asset_id, trade.taker_asset_id]:
            return market, "Yes"

    return None, None


async def send_notification(bot: Bot, chat_id: int, trade: Trade, label: str):
    """Send trade notification to Telegram."""
    market, outcome = get_market_for_trade(trade)

    enriched = EnrichedTrade(trade=trade, market=market, outcome=outcome)
    message = format_trade_alert(enriched, label)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        print(f"❌ Failed to send: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Mock trade test with real data")
    parser.add_argument("--interval", type=int, default=15, help="Seconds between trades (default: 15)")
    parser.add_argument("--min-usd", type=float, default=0, help="Minimum USD value to notify (default: 0)")
    parser.add_argument("--count", type=int, default=0, help="Number of trades to send (0=infinite)")
    args = parser.parse_args()

    print("=" * 60)
    print("  POLYBOT - Real Trade Mock Test")
    print("=" * 60)
    print(f"\n⚙️  Settings:")
    print(f"   Interval: {args.interval}s")
    print(f"   Min USD: ${args.min_usd}")
    print(f"   Count: {'∞' if args.count == 0 else args.count}")

    # Initialize
    bot = Bot(TELEGRAM_BOT_TOKEN)
    await db.connect()

    me = await bot.get_me()
    print(f"\n🤖 Bot: @{me.username}")

    # Get tracked wallets from real trades
    real_addresses = list(set(t["maker"] for t in REAL_TRADES))

    # Setup: track all makers from real trades
    print(f"\n📝 Setting up {len(real_addresses)} wallets from real trades...")

    cursor = await db._conn.execute("SELECT chat_id FROM users WHERE is_active = 1")
    users = await cursor.fetchall()

    if not users:
        print("❌ No users! Send /start to @polyoctant_bot first")
        await db.close()
        return

    # Add wallets for tracking
    for i, addr in enumerate(real_addresses[:5]):  # Track first 5
        label = f"trader{i+1}"
        for user in users:
            await db.add_tracked_wallet(user["chat_id"], addr, label)
        print(f"   {label}: {addr[:12]}...")

    # Parse trades and filter by min USD
    trades = [parse_trade(t) for t in REAL_TRADES]
    trades = [t for t in trades if t.usdc_value >= args.min_usd]

    print(f"\n📊 {len(trades)} trades >= ${args.min_usd}")

    if not trades:
        print("❌ No trades match filter!")
        await db.close()
        return

    # Send trades
    print(f"\n🚀 Sending trades every {args.interval}s...")
    print("   Press Ctrl+C to stop\n")

    sent = 0
    try:
        while True:
            trade = random.choice(trades)

            # Get watchers
            watchers = await db.get_users_tracking_wallet(trade.maker)

            if watchers:
                emoji = "🟢" if trade.side == "BUY" else "🔴"
                print(f"#{sent+1} {emoji} {trade.side} ${trade.usdc_value:.2f} from {trade.maker[:10]}...")

                for chat_id, label in watchers:
                    success = await send_notification(bot, chat_id, trade, label or "trader")
                    if success:
                        print(f"   ✅ Sent to {chat_id}")

                sent += 1

            if args.count > 0 and sent >= args.count:
                print(f"\n✅ Sent {sent} trades")
                break

            await asyncio.sleep(args.interval)

    except KeyboardInterrupt:
        print(f"\n\n🛑 Stopped after {sent} trades")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
