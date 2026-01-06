#!/usr/bin/env python3
"""
LIVE trade monitor with custom subscription filters.

Config file: config.json
{
  "subscriptions": {
    "min_usd": 10,              // Minimum trade amount
    "max_usd": null,            // Maximum trade amount (null = no limit)
    "side": null,               // "BUY", "SELL", or null for both
    "tracked_wallets": [        // Only these wallets (empty = all)
      "0x1234...",
      "0xabcd..."
    ],
    "keywords": [               // Market must contain keyword (empty = all)
      "Bitcoin",
      "Trump"
    ]
  },
  "settings": {
    "interval": 15,
    "limit": 20
  }
}

Usage:
    uv run python test_live.py
    uv run python test_live.py --min-usd 100
"""

import asyncio
import argparse
import json
from pathlib import Path
from telegram import Bot

from src.config import TELEGRAM_BOT_TOKEN, logger
from src.storage.database import db
from src.storage.models import EnrichedTrade
from src.bot.messages import format_trade_alert
from src.api.envio import envio_client
from src.api.gamma import gamma_client


CONFIG_FILE = Path(__file__).parent / "config.json"


def load_config() -> dict:
    """Load config from JSON file."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {
        "subscriptions": {
            "min_usd": 10,
            "max_usd": None,
            "side": None,
            "tracked_wallets": [],
            "keywords": [],
        },
        "settings": {
            "interval": 15,
            "limit": 20,
        }
    }


def save_config(config: dict) -> None:
    """Save config to JSON file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def matches_filters(trade, market, config: dict) -> tuple[bool, str]:
    """Check if trade matches subscription filters. Returns (match, reason)."""
    subs = config.get("subscriptions", {})

    # Min USD filter
    min_usd = subs.get("min_usd", 0)
    if trade.usdc_value < min_usd:
        return False, f"amount ${trade.usdc_value:.2f} < ${min_usd}"

    # Max USD filter
    max_usd = subs.get("max_usd")
    if max_usd and trade.usdc_value > max_usd:
        return False, f"amount ${trade.usdc_value:.2f} > ${max_usd}"

    # Side filter (BUY/SELL)
    side_filter = subs.get("side")
    if side_filter and trade.side != side_filter.upper():
        return False, f"side {trade.side} != {side_filter}"

    # Tracked wallets filter
    tracked = subs.get("tracked_wallets", [])
    if tracked:
        tracked_lower = [w.lower() for w in tracked]
        if trade.maker.lower() not in tracked_lower:
            return False, "wallet not in tracked list"

    # Keywords filter
    keywords = subs.get("keywords", [])
    if keywords and market:
        question = market.question.lower()
        if not any(kw.lower() in question for kw in keywords):
            return False, f"no keyword match in '{market.question[:30]}...'"

    return True, "matched"


async def send_notification(bot: Bot, chat_id: int, enriched: EnrichedTrade, label: str):
    """Send trade notification to Telegram."""
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
        print(f"❌ Send failed: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Live trade monitor with custom filters")
    parser.add_argument("--min-usd", type=float, help="Override min USD filter")
    parser.add_argument("--max-usd", type=float, help="Override max USD filter")
    parser.add_argument("--side", choices=["BUY", "SELL"], help="Filter by side")
    parser.add_argument("--wallet", action="append", help="Track specific wallet(s)")
    parser.add_argument("--keyword", action="append", help="Filter by market keyword(s)")
    parser.add_argument("--interval", type=int, help="Poll interval seconds")
    parser.add_argument("--limit", type=int, help="Trades per poll")
    args = parser.parse_args()

    # Load config
    config = load_config()

    # Override with CLI args
    if args.min_usd is not None:
        config["subscriptions"]["min_usd"] = args.min_usd
    if args.max_usd is not None:
        config["subscriptions"]["max_usd"] = args.max_usd
    if args.side:
        config["subscriptions"]["side"] = args.side
    if args.wallet:
        config["subscriptions"]["tracked_wallets"] = args.wallet
    if args.keyword:
        config["subscriptions"]["keywords"] = args.keyword
    if args.interval:
        config["settings"]["interval"] = args.interval
    if args.limit:
        config["settings"]["limit"] = args.limit

    subs = config["subscriptions"]
    settings = config["settings"]

    print("=" * 60)
    print("  POLYBOT - LIVE Trade Monitor")
    print("=" * 60)
    print(f"\n📋 Subscription Filters:")
    print(f"   Min USD: ${subs.get('min_usd', 0)}")
    print(f"   Max USD: ${subs.get('max_usd') or '∞'}")
    print(f"   Side: {subs.get('side') or 'ALL'}")
    print(f"   Wallets: {len(subs.get('tracked_wallets', [])) or 'ALL'}")
    print(f"   Keywords: {subs.get('keywords') or 'ALL'}")
    print(f"\n⚙️  Settings:")
    print(f"   Interval: {settings['interval']}s")
    print(f"   Limit: {settings['limit']}")

    # Initialize
    bot = Bot(TELEGRAM_BOT_TOKEN)
    await db.connect()

    me = await bot.get_me()
    print(f"\n🤖 Bot: @{me.username}")

    # Get chat_id
    cursor = await db._conn.execute("SELECT chat_id FROM users WHERE is_active = 1 LIMIT 1")
    user = await cursor.fetchone()

    if not user:
        print("❌ No users! Send /start to @polyoctant_bot first")
        await db.close()
        return

    chat_id = user["chat_id"]
    print(f"📱 Sending to: {chat_id}")

    seen_trades = set()

    print(f"\n🔴 LIVE monitoring started...")
    print("   Press Ctrl+C to stop\n")

    sent_count = 0
    skipped_count = 0

    try:
        while True:
            trades = await envio_client.get_recent_trades(limit=settings["limit"])

            for trade in trades:
                if trade.id in seen_trades:
                    continue
                seen_trades.add(trade.id)

                if len(seen_trades) > 1000:
                    seen_trades = set(list(seen_trades)[-500:])

                # Enrich with market data
                market = await gamma_client.get_market_by_token(trade.outcome_token_id)
                outcome = None
                if market:
                    outcome = gamma_client.get_outcome_name(market, trade.outcome_token_id)

                # Check filters
                matched, reason = matches_filters(trade, market, config)

                if not matched:
                    skipped_count += 1
                    continue

                enriched = EnrichedTrade(trade=trade, market=market, outcome=outcome)

                # Console output
                emoji = "🟢" if trade.side == "BUY" else "🔴"
                market_name = market.question[:50] + "..." if market else "Unknown"
                print(f"{emoji} ${trade.usdc_value:.0f} {trade.side} | {market_name}")

                # Send to Telegram
                label = f"{trade.maker[:8]}"
                success = await send_notification(bot, chat_id, enriched, label)
                if success:
                    sent_count += 1
                    print(f"   ✅ Sent (#{sent_count}, skipped {skipped_count})\n")

            await asyncio.sleep(settings["interval"])

    except KeyboardInterrupt:
        print(f"\n\n🛑 Stopped")
        print(f"   Sent: {sent_count}")
        print(f"   Skipped: {skipped_count}")
    finally:
        await envio_client.close()
        await gamma_client.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
