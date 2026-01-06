#!/usr/bin/env python3
"""
Mock test that sends REAL Telegram notifications with fake trade data.
This lets you test the full flow without waiting for real trades.

Usage:
    uv run python test_tg_mock.py
"""

import asyncio
import random
from datetime import datetime, timezone

from telegram import Bot

from src.config import TELEGRAM_BOT_TOKEN, logger
from src.storage.database import db
from src.storage.models import Trade, EnrichedTrade, Market
from src.bot.messages import format_trade_alert


# Mock wallet addresses
MOCK_WALLETS = [
    ("0x1234567890abcdef1234567890abcdef12345678", "whale1"),
    ("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", "smartmoney"),
]

# Mock markets
MOCK_MARKETS = [
    Market(
        condition_id="0xabc123",
        question="Will Bitcoin reach $100k by end of 2025?",
        slug="bitcoin-100k-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.65", "0.35"],
        clob_token_ids=["token_yes_btc", "token_no_btc"],
        category="Crypto",
    ),
    Market(
        condition_id="0xdef456",
        question="Will Trump win 2024 election?",
        slug="trump-2024",
        outcomes=["Yes", "No"],
        outcome_prices=["0.52", "0.48"],
        clob_token_ids=["token_yes_trump", "token_no_trump"],
        category="Politics",
    ),
    Market(
        condition_id="0x789ghi",
        question="Will ETH flip BTC market cap in 2025?",
        slug="eth-flip-btc-2025",
        outcomes=["Yes", "No"],
        outcome_prices=["0.12", "0.88"],
        clob_token_ids=["token_yes_flip", "token_no_flip"],
        category="Crypto",
    ),
]


def generate_mock_trade(wallet_address: str) -> Trade:
    """Generate a random mock trade."""
    market = random.choice(MOCK_MARKETS)
    is_buy = random.choice([True, False])
    outcome_idx = random.randint(0, 1)

    usdc_amount = random.randint(1000, 50000) * 1_000_000
    price = float(market.outcome_prices[outcome_idx])
    token_amount = int(usdc_amount / price)

    if is_buy:
        maker_asset_id = "0"
        taker_asset_id = market.clob_token_ids[outcome_idx]
        maker_amount = usdc_amount
        taker_amount = token_amount
    else:
        maker_asset_id = market.clob_token_ids[outcome_idx]
        taker_asset_id = "0"
        maker_amount = token_amount
        taker_amount = usdc_amount

    tx_hash = f"0x{''.join(random.choices('0123456789abcdef', k=64))}"

    return Trade(
        id=f"{tx_hash}-{random.randint(0, 100)}",
        order_hash=f"0x{''.join(random.choices('0123456789abcdef', k=64))}",
        maker=wallet_address.lower(),
        taker=f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
        maker_asset_id=maker_asset_id,
        taker_asset_id=taker_asset_id,
        maker_amount_filled=maker_amount,
        taker_amount_filled=taker_amount,
        timestamp=int(datetime.now(timezone.utc).timestamp()),
        tx_hash=tx_hash,
        log_index=random.randint(0, 100),
    )


def get_mock_market(token_id: str) -> Market | None:
    for market in MOCK_MARKETS:
        if token_id in market.clob_token_ids:
            return market
    return None


async def send_mock_notification(bot: Bot, chat_id: int, enriched: EnrichedTrade, label: str):
    """Send a mock trade notification to Telegram."""
    try:
        message = format_trade_alert(enriched, label)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        print(f"✅ Sent notification to {chat_id}")
    except Exception as e:
        print(f"❌ Failed to send: {e}")


async def main():
    print("=" * 60)
    print("  POLYBOT - Mock Telegram Test")
    print("=" * 60)

    # Initialize
    bot = Bot(TELEGRAM_BOT_TOKEN)
    await db.connect()

    # Get bot info
    me = await bot.get_me()
    print(f"\n🤖 Bot: @{me.username}")

    # Add mock wallets for current user
    print("\n📝 Setting up mock wallets...")

    # Get all users from database
    cursor = await db._conn.execute("SELECT chat_id, username FROM users WHERE is_active = 1")
    users = await cursor.fetchall()

    if not users:
        print("❌ No users registered! Send /start to @polyoctant_bot first")
        await db.close()
        return

    print(f"   Found {len(users)} registered user(s)")

    # Add mock wallets for each user
    for user in users:
        chat_id = user["chat_id"]
        username = user["username"] or "unknown"
        print(f"\n👤 User: @{username} (chat_id: {chat_id})")

        for address, label in MOCK_WALLETS:
            success = await db.add_tracked_wallet(chat_id, address, label)
            status = "added" if success else "exists"
            print(f"   {label}: {address[:10]}... [{status}]")

    # Generate and send mock trades
    print("\n" + "=" * 60)
    print("  Generating mock trades (Ctrl+C to stop)")
    print("=" * 60)

    try:
        trade_count = 0
        while True:
            # Pick random wallet
            wallet_address, label = random.choice(MOCK_WALLETS)

            # Generate trade
            trade = generate_mock_trade(wallet_address)
            market = get_mock_market(trade.outcome_token_id)

            outcome = None
            if market:
                try:
                    idx = market.clob_token_ids.index(trade.outcome_token_id)
                    outcome = market.outcomes[idx]
                except (ValueError, IndexError):
                    pass

            enriched = EnrichedTrade(trade=trade, market=market, outcome=outcome)

            # Print to console
            trade_count += 1
            emoji = "🟢" if trade.side == "BUY" else "🔴"
            print(f"\n#{trade_count} {emoji} {label} {trade.side} ${trade.usdc_value:,.0f}")

            # Get users tracking this wallet
            watchers = await db.get_users_tracking_wallet(wallet_address)

            # Send to all watchers
            for chat_id, user_label in watchers:
                await send_mock_notification(bot, chat_id, enriched, user_label or label)

            # Wait before next trade
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        print("\n\n🛑 Stopped")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
